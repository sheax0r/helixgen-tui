"""ToneEditorScreen: navigate a tone's signal chain and tweak block params.

Opened with Enter on a Library tone. The top band renders the chain
**horizontally**, left-to-right: an input (head) node, then one row per lane
(both DSP paths stacked when the tone is parallel-routed, split/join drawn with
``+``/``-`` connectors), then the output (terminal, level/pan) node. The cursor
starts on the first block; left/right walk along a lane (out to the input node
on the left, the output node on the right), up/down move across lanes. Tab
switches to the params inspector below, whose left/right nudge the selected
param (float 0.01 clamped to [0,1]; int +/-1; bool toggles) and Enter opens
inline manual entry.

Selecting the output node shows its level/pan in the inspector; selecting the
input node shows the instrument source read-only. Edits are held in a working
set and written to the library ``.hsp`` only on an explicit ``s``/``ctrl+s`` —
never autosaved, never pushed to the device. A dirty indicator shows while there
are unsaved edits and a confirm guards leaving with them.

Scope here (v1, Task 5) is chain rendering + navigation + param editing. The
structural verbs (add/remove/swap/bypass) and output writes are wired in Task 6.

Markup safety (repo bug class #12): the header is a ``markup=False`` Static, the
chain surface is a ``rich.text.Text`` (styles, never markup) and every param
cell is a ``rich.text.Text`` — a bracket-bearing model/param name renders
literally instead of being stripped / crashing the screen.
"""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from helixgen_tui.core.models import BlockVM, ChainVM, MutationPlan, OpResult, ParamChange, ParamVM
from helixgen_tui.widgets.block_picker_modal import BlockPickerModal
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter

_CHAIN_ID = "editor-chain"
_CHAIN_WRAP_ID = "editor-chain-wrap"
_PARAMS_ID = "editor-params"
_HEADER_ID = "editor-header"
_ENTRY_ID = "editor-entry"

_FLOAT_STEP = 0.01
# Output main-out level is dB, roughly [-120, 20]; nudge in 0.5 dB steps.
_LEVEL_STEP = 0.5
_LEVEL_MIN = -120.0
_LEVEL_MAX = 20.0

_DESC_MAX = 100


def _compact(text: str) -> str:
    """Collapse all whitespace/newlines to single spaces and truncate.

    A tone description can be many paragraphs; the header renders it on one
    line, so we flatten it and cap the length (with an ellipsis) rather than
    let it expand the fixed-height header and crowd out the tables."""
    flat = " ".join(text.split())
    if len(flat) > _DESC_MAX:
        return flat[: _DESC_MAX - 1].rstrip() + "…"
    return flat


def _fmt_value(value: object) -> str:
    """Render a param value for a table cell: floats to 2dp, bools as on/off."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _clamp_float(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 2)


def _clamp_level(value: float) -> float:
    return round(min(_LEVEL_MAX, max(_LEVEL_MIN, value)), 1)


def _coerce(ptype: str, raw: str) -> object:
    """Parse a manually-typed string into ``ptype``, clamping floats to [0,1].

    Raises ``ValueError`` on input that isn't valid for the type (surfaced as an
    inline error)."""
    text = raw.strip()
    if ptype == "float":
        return _clamp_float(float(text))
    if ptype == "int":
        # reject non-integers ("1.5") rather than silently truncating
        return int(text)
    if ptype == "bool":
        low = text.lower()
        if low in ("1", "true", "on", "yes"):
            return True
        if low in ("0", "false", "off", "no"):
            return False
        raise ValueError(f"{raw!r} is not a boolean")
    return raw


class ToneEditorScreen(Screen):
    """Full-screen chain navigator + param editor for one tone."""

    DEFAULT_CSS = f"""
    ToneEditorScreen #{_HEADER_ID} {{
        height: 4;
        padding: 0 1;
        background: $panel;
        color: $text;
    }}

    ToneEditorScreen #{_CHAIN_WRAP_ID} {{
        height: auto;
        max-height: 40%;
        overflow-x: auto;
        overflow-y: auto;
    }}

    ToneEditorScreen #{_CHAIN_ID} {{
        width: auto;
        height: auto;
        padding: 0 1;
    }}

    ToneEditorScreen #{_PARAMS_ID} {{
        width: 100%;
        height: 1fr;
    }}

    ToneEditorScreen .-active-pane {{
        border: round $accent;
    }}

    ToneEditorScreen #{_ENTRY_ID} {{
        dock: bottom;
        height: 3;
    }}

    ToneEditorScreen #bottom-bars {{
        dock: bottom;
        height: 2;
    }}
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("left", "horizontal(-1)", "Left", show=False),
        Binding("right", "horizontal(1)", "Right", show=False),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("enter", "manual_entry", "Edit value"),
        Binding("a", "add_block", "Add block"),
        Binding("x", "remove_block", "Remove"),
        Binding("b", "toggle_bypass", "Bypass"),
        Binding("w", "swap_model", "Swap"),
        Binding("s", "save", "Save"),
        Binding("ctrl+s", "save", "Save", show=False),
        Binding("escape", "leave", "Back"),
    ]

    def __init__(self, tone_id: str) -> None:
        self._tone_id = tone_id
        self._chain: ChainVM | None = None
        # Chain-navigator cursor: which zone (input head / a block / output
        # terminal), and, when on a block, which lane (path index) and column
        # (block index within the lane).
        self._zone = "blocks"  # "input" | "blocks" | "output"
        self._lane = 0
        self._col = 0
        self._param_index = 0
        # Working edits: (model, path, position, param) -> new value. Present
        # only while the value differs from disk (an edit back to the on-disk
        # value prunes itself), so ``bool(self._edits)`` is the dirty flag.
        self._edits: dict[tuple[str, int, int, str], object] = {}
        # Pending output-node edit (level, pan), held like a param edit and
        # flushed on save via ``set_output``; ``None`` when the output matches
        # disk. Part of the dirty flag.
        self._output_edit: tuple[float, float] | None = None
        self._editing = False
        self._focus = "blocks"  # "blocks" (chain navigator) | "params"
        super().__init__()

    # -- compose -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id=_HEADER_ID, markup=False)
        chain = Static("", id=_CHAIN_ID, markup=False)
        params = DataTable(id=_PARAMS_ID, cursor_type="row")
        # Non-focusable so the screen's own bindings own every nav/edit key;
        # a focused DataTable would swallow up/down/left/right/enter/tab.
        chain.can_focus = False
        params.can_focus = False
        with ScrollableContainer(id=_CHAIN_WRAP_ID):
            yield chain
        yield params
        with Vertical(id="bottom-bars"):
            yield StatusFooter()
            yield Footer()

    def on_mount(self) -> None:
        params = self.query_one(f"#{_PARAMS_ID}", DataTable)
        params.add_columns("Param", "Value")
        # Belt-and-suspenders: ensure nothing holds focus so keys reach us.
        self.set_focus(None)

        footer = self.query_one(StatusFooter)
        footer.set_device_text(self.app.device_text)

        self._chain = self.app.core.editor.get_chain(self._tone_id)
        # Cursor starts on the first block; fall back to the input node if the
        # first lane is empty (or the tone has no chain at all).
        self._zone = "blocks"
        self._lane = 0
        self._col = 0
        if self._selected_block() is None:
            self._zone = "input"
        self._render_header()
        self._render_chain()
        self._rebuild_params_table()
        self._reflect_focus()

    # -- selection ---------------------------------------------------------

    def _current_lane(self) -> object | None:
        if self._chain is None or not self._chain.paths:
            return None
        self._lane = max(0, min(self._lane, len(self._chain.paths) - 1))
        return self._chain.paths[self._lane]

    def _selected_block(self) -> BlockVM | None:
        if self._zone != "blocks":
            return None
        lane = self._current_lane()
        if lane is None or not lane.blocks:
            return None
        self._col = max(0, min(self._col, len(lane.blocks) - 1))
        return lane.blocks[self._col]

    def _selected_params(self) -> list[ParamVM]:
        block = self._selected_block()
        return list(block.params) if block is not None else []

    def _selected_param(self) -> ParamVM | None:
        params = self._selected_params()
        if not params:
            return None
        self._param_index = max(0, min(self._param_index, len(params) - 1))
        return params[self._param_index]

    def _sel_key(self) -> tuple:
        if self._zone == "input":
            return ("input",)
        if self._zone == "output":
            return ("output",)
        return ("block", self._lane, self._col)

    def _current_value(self, block: BlockVM, param: ParamVM) -> object:
        """The working value: a pending edit if present, else the on-disk value."""
        key = (block.model, block.path, block.position, param.name)
        return self._edits.get(key, param.value)

    @property
    def is_dirty(self) -> bool:
        return bool(self._edits) or self._output_edit is not None

    def _output_working(self) -> tuple[float, float] | None:
        """The working output (level, pan): a pending edit if present, else the
        on-disk output; ``None`` when the tone has no readable output node."""
        if self._chain is None or self._chain.output is None:
            return None
        if self._output_edit is not None:
            return self._output_edit
        out = self._chain.output
        return (out.level, out.pan)

    # -- rendering ---------------------------------------------------------

    def _render_header(self) -> None:
        header = self.query_one(f"#{_HEADER_ID}", Static)
        if self._chain is None:
            header.update("(this tone has no editable chain)")
            return
        c = self._chain
        setlists = ", ".join(c.setlists) if c.setlists else "-"
        dirty = "   * unsaved" if self.is_dirty else ""
        lines = [
            f"{c.name}{dirty}",
            f"Guitar: {c.guitar or '-'}   Setlists: {setlists}",
            f"Description: {_compact(c.description) if c.description else '-'}",
        ]
        header.update("\n".join(lines))

    def _input_label(self) -> str:
        src = self._chain.input_source if self._chain else None
        return f"IN:{src or '?'}"

    def _output_label(self) -> str:
        working = self._output_working()
        if working is None:
            return "OUT —"
        level, pan = working
        return f"OUT L{level:.1f} P{pan:.2f}"

    @staticmethod
    def _block_label(block: BlockVM) -> str:
        suffix = "" if block.enabled else " (byp)"
        return f"[{block.display}{suffix}]"

    def _render_chain(self) -> None:
        """Render the chain as a horizontal, markup-safe ``Text`` band.

        Input head node on the left, one row per lane (blocks joined by ``-``
        connectors), output terminal node on the right. When the tone is
        parallel-routed (>1 lane) the split/join columns are marked with ``+``.
        The selected node is drawn ``reverse``."""
        static = self.query_one(f"#{_CHAIN_ID}", Static)
        if self._chain is None:
            static.update("(this tone has no editable chain)")
            return
        sel = self._sel_key()
        paths = self._chain.paths
        multi = len(paths) > 1
        in_label = self._input_label()
        out_label = self._output_label()

        text = Text(no_wrap=True)
        for i, path in enumerate(paths or ((),)):
            if i > 0:
                text.append("\n")
            # input column: label on the first lane, padding underneath
            if i == 0:
                text.append(in_label, style="reverse" if sel == ("input",) else "")
            else:
                text.append(" " * len(in_label))
            text.append(" +-" if multi else " -")
            blocks = getattr(path, "blocks", ())
            for j, block in enumerate(blocks):
                text.append(" - " if j > 0 else " ")
                text.append(
                    self._block_label(block),
                    style="reverse" if sel == ("block", i, j) else "",
                )
            text.append(" -+" if multi else " -")
            # output column: label on the first lane, padding underneath
            text.append(" ")
            if i == 0:
                text.append(out_label, style="reverse" if sel == ("output",) else "")
            else:
                text.append(" " * len(out_label))
        static.update(text)

    def _rebuild_params_table(self) -> None:
        """Populate the inspector from the current selection.

        Block → its editable params; output node → level/pan; input node →
        the instrument source (read-only). Output/input rows are display-only
        here; writing them is Task 6."""
        table = self.query_one(f"#{_PARAMS_ID}", DataTable)
        table.clear()
        if self._chain is None:
            return
        if self._zone == "input":
            table.add_row(Text("Source"), Text(self._chain.input_source or "?"))
            return
        if self._zone == "output":
            working = self._output_working()
            if working is not None:
                level, pan = working
                table.add_row(Text("Level"), Text(f"{level:.1f}"))
                table.add_row(Text("Pan"), Text(f"{pan:.2f}"))
                table.move_cursor(row=min(self._param_index, 1))
            return
        block = self._selected_block()
        params = self._selected_params()
        for param in params:
            value = self._current_value(block, param) if block is not None else param.value
            table.add_row(Text(param.name), Text(_fmt_value(value)))
        if params:
            table.move_cursor(row=min(self._param_index, len(params) - 1))

    # -- navigation --------------------------------------------------------

    def action_switch_pane(self) -> None:
        if self._editing:
            return
        self._focus = "params" if self._focus == "blocks" else "blocks"
        self._reflect_focus()

    def _reflect_focus(self) -> None:
        # A visible cue for which pane is active: border the active surface.
        wrap = self.query_one(f"#{_CHAIN_WRAP_ID}", ScrollableContainer)
        params = self.query_one(f"#{_PARAMS_ID}", DataTable)
        wrap.set_class(self._focus == "blocks", "-active-pane")
        params.set_class(self._focus == "params", "-active-pane")

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def _move_cursor(self, delta: int) -> None:
        """up/down: in the chain navigator move across lanes; in the params
        inspector move the param selection."""
        if self._editing:
            return
        if self._focus == "blocks":
            if self._zone == "blocks" and self._chain is not None and self._chain.paths:
                npaths = len(self._chain.paths)
                self._lane = max(0, min(self._lane + delta, npaths - 1))
                lane = self._chain.paths[self._lane]
                self._col = max(0, min(self._col, max(0, len(lane.blocks) - 1)))
            # input/output are single nodes: vertical does nothing.
            self._param_index = 0
            self._render_chain()
            self._rebuild_params_table()
        else:
            n = self._param_pane_row_count()
            if n == 0:
                return
            self._param_index = max(0, min(self._param_index + delta, n - 1))
            self.query_one(f"#{_PARAMS_ID}", DataTable).move_cursor(row=self._param_index)

    def _param_pane_row_count(self) -> int:
        """How many selectable/editable rows the inspector holds for the current
        selection: a block's params, the output's level+pan, or none (the input
        node's source is read-only)."""
        if self._zone == "output":
            return 2 if (self._chain is not None and self._chain.output is not None) else 0
        if self._zone == "input":
            return 0
        return len(self._selected_params())

    def action_horizontal(self, direction: int) -> None:
        """left/right: in the params inspector nudge; in the chain navigator
        walk along the lane (out to the input/output nodes at the ends)."""
        if self._editing:
            return
        if self._focus == "params":
            self._nudge(direction)
            return
        self._chain_move_h(direction)

    def _chain_move_h(self, direction: int) -> None:
        if self._chain is None:
            return
        lane = self._current_lane()
        blocks = lane.blocks if lane is not None else ()
        if direction > 0:  # right
            if self._zone == "input":
                self._zone = "blocks" if blocks else "output"
                self._col = 0
            elif self._zone == "blocks":
                if self._col < len(blocks) - 1:
                    self._col += 1
                else:
                    self._zone = "output"
            # output: already at the terminal, stay
        else:  # left
            if self._zone == "output":
                if blocks:
                    self._zone = "blocks"
                    self._col = len(blocks) - 1
                else:
                    self._zone = "input"
            elif self._zone == "blocks":
                if self._col > 0:
                    self._col -= 1
                else:
                    self._zone = "input"
            # input: already at the head, stay
        self._param_index = 0
        self._render_chain()
        self._rebuild_params_table()

    # -- value editing -----------------------------------------------------

    def _set_value(self, block: BlockVM, param: ParamVM, value: object) -> None:
        """Record a working edit, pruning it when it matches the on-disk value.

        Floats are compared at display precision (2dp): an on-disk value like
        0.333 shows as 0.33, so nudging up then down lands on 0.33 — without
        this the edit would never prune and a "no-op" save would rewrite the
        value to 0.33 (silent drift)."""
        key = (block.model, block.path, block.position, param.name)
        if param.type == "float" and isinstance(value, (int, float)) and isinstance(
            param.value, (int, float)
        ):
            unchanged = _clamp_float(float(value)) == _clamp_float(float(param.value))
        else:
            unchanged = value == param.value
        if unchanged:
            self._edits.pop(key, None)
        else:
            self._edits[key] = value
        self._render_header()
        self._rebuild_params_table()

    def _set_output_edit(self, level: float, pan: float) -> None:
        """Record a working output edit, pruning it when it matches disk."""
        out = self._chain.output if self._chain else None
        if (
            out is not None
            and _clamp_level(level) == _clamp_level(out.level)
            and _clamp_float(pan) == _clamp_float(out.pan)
        ):
            self._output_edit = None
        else:
            self._output_edit = (level, pan)
        self._render_header()
        self._render_chain()
        self._rebuild_params_table()

    def _nudge_output(self, direction: int) -> None:
        working = self._output_working()
        if working is None:
            return
        level, pan = working
        if self._param_index == 0:  # Level (dB)
            level = _clamp_level(level + direction * _LEVEL_STEP)
        else:  # Pan (0..1)
            pan = _clamp_float(pan + direction * _FLOAT_STEP)
        self._set_output_edit(level, pan)

    def _nudge(self, direction: int) -> None:
        if self._zone == "output":
            self._nudge_output(direction)
            return
        block = self._selected_block()
        param = self._selected_param()
        if block is None or param is None:
            return
        current = self._current_value(block, param)
        if param.type == "bool":
            new_value: object = not bool(current)
        elif param.type == "int":
            new_value = int(current) + direction
        elif param.type == "float":
            new_value = _clamp_float(float(current) + direction * _FLOAT_STEP)
        else:
            return  # str params aren't nudgeable; use manual entry
        self._set_value(block, param, new_value)

    def action_manual_entry(self) -> None:
        if self._editing or self._focus != "params":
            return
        if self._zone == "output":
            self._open_output_entry()
            return
        block = self._selected_block()
        param = self._selected_param()
        if block is None or param is None:
            return
        self._editing = True
        current = self._current_value(block, param)
        entry = Input(value=_fmt_value(current), id=_ENTRY_ID)
        # escape(): border_title is console-markup-parsed, so a param name
        # carrying brackets (e.g. "[/]") would raise MarkupError on assignment.
        entry.border_title = escape(f"edit {param.name}")
        self.mount(entry)
        entry.focus()

    def _open_output_entry(self) -> None:
        working = self._output_working()
        if working is None:
            return
        self._editing = True
        idx = min(self._param_index, 1)
        label = "Level" if idx == 0 else "Pan"
        value = f"{working[idx]:.1f}" if idx == 0 else f"{working[idx]:.2f}"
        entry = Input(value=value, id=_ENTRY_ID)
        entry.border_title = f"edit {label}"
        self.mount(entry)
        entry.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _ENTRY_ID:
            return
        if self._zone == "output":
            self._submit_output_entry(event.value)
            return
        block = self._selected_block()
        param = self._selected_param()
        raw = event.value
        if block is None or param is None:
            self._close_entry()
            return
        try:
            value = _coerce(param.type, raw)
        except ValueError:
            self.app.report_op(
                OpResult(ok=False, message=f"invalid {param.type} value: {raw!r}")
            )
            # keep the entry open so the user can correct it
            return
        self._set_value(block, param, value)
        self._close_entry()

    def _submit_output_entry(self, raw: str) -> None:
        working = self._output_working()
        if working is None:
            self._close_entry()
            return
        try:
            v = float(raw.strip())
        except ValueError:
            self.app.report_op(OpResult(ok=False, message=f"invalid value: {raw!r}"))
            return  # keep the entry open to correct it
        level, pan = working
        if min(self._param_index, 1) == 0:
            level = _clamp_level(v)
        else:
            pan = _clamp_float(v)
        self._set_output_edit(level, pan)
        self._close_entry()

    def _close_entry(self) -> None:
        self._editing = False
        try:
            self.query_one(f"#{_ENTRY_ID}", Input).remove()
        except Exception:  # noqa: BLE001 — already gone
            pass
        self._reflect_focus()

    # -- structural verbs --------------------------------------------------

    def _is_parallel(self) -> bool:
        """A parallel-routed tone (>1 lane): add/remove refuse before touching
        the adapter, so nothing is recorded and no wrong-slot write can occur."""
        return self._chain is not None and len(self._chain.paths) > 1

    def _reload_chain(self) -> None:
        """Re-read the chain from disk and drop any working edits — used after a
        structural write (which persists immediately and may shift positions)
        and after a save."""
        self._edits.clear()
        self._output_edit = None
        self._chain = self.app.core.editor.get_chain(self._tone_id)
        self._render_header()
        self._render_chain()
        self._rebuild_params_table()

    def action_add_block(self) -> None:
        if self._editing or self._chain is None:
            return
        block = self._selected_block()
        if block is None:
            return  # input/output node: nothing to add after
        if self._is_parallel():
            self.app.report_op(
                OpResult(ok=False, message="add not supported on a parallel-routed path")
            )
            return
        catalog = self.app.core.editor.list_block_catalog()
        self.app.push_screen(BlockPickerModal(catalog), self._on_add_model)

    def _on_add_model(self, model: str | None) -> None:
        if not model:
            return
        block = self._selected_block()
        result = self.app.core.editor.add_block(self._tone_id, block, model)
        self.app.report_op(result)
        if result.ok:
            self._reload_chain()

    def action_remove_block(self) -> None:
        if self._editing or self._chain is None:
            return
        block = self._selected_block()
        if block is None:
            return
        if self._is_parallel():
            self.app.report_op(
                OpResult(ok=False, message="remove not supported on a parallel-routed path")
            )
            return
        result = self.app.core.editor.remove_block(self._tone_id, block)
        self.app.report_op(result)
        if result.ok:
            self._reload_chain()

    def action_toggle_bypass(self) -> None:
        if self._editing or self._chain is None:
            return
        block = self._selected_block()
        if block is None:
            return
        result = self.app.core.editor.set_bypass(self._tone_id, block, not block.enabled)
        self.app.report_op(result)
        if result.ok:
            self._reload_chain()

    def action_swap_model(self) -> None:
        if self._editing or self._chain is None:
            return
        block = self._selected_block()
        if block is None:
            return
        catalog = self.app.core.editor.list_block_catalog()
        self.app.push_screen(BlockPickerModal(catalog), self._on_swap_model)

    def _on_swap_model(self, model: str | None) -> None:
        if not model:
            return
        block = self._selected_block()
        if block is None:
            return
        result = self.app.core.editor.swap_model(self._tone_id, block, model)
        self.app.report_op(result)
        if result.ok:
            self._reload_chain()

    # -- save / leave ------------------------------------------------------

    def _pending_changes(self) -> list[ParamChange]:
        return [
            ParamChange(model=model, path=path, position=position, param=param, value=value)
            for (model, path, position, param), value in self._edits.items()
        ]

    def action_save(self) -> None:
        if self._editing:
            return
        if not self._edits and self._output_edit is None:
            self.app.report_op(OpResult(ok=True, message="nothing to save"))
            return
        all_ok = True
        if self._edits:
            result = self.app.core.editor.save_params(self._tone_id, self._pending_changes())
            self.app.report_op(result)
            all_ok = all_ok and result.ok
        if self._output_edit is not None:
            level, pan = self._output_edit
            result = self.app.core.editor.set_output(self._tone_id, level, pan)
            self.app.report_op(result)
            all_ok = all_ok and result.ok
        if all_ok:
            # Rebase to the saved values so the display stays and dirty clears.
            self._reload_chain()

    def action_leave(self) -> None:
        if self._editing:
            self._close_entry()
            return
        if not self._edits and self._output_edit is None:
            self.app.pop_screen()
            return
        n = len(self._edits) + (1 if self._output_edit is not None else 0)
        plan = MutationPlan(
            title="Discard unsaved changes?",
            lines=(f"{n} unsaved edit(s) will be lost.",),
        )
        self.app.push_screen(ConfirmModal(plan), self._confirm_leave)

    def _confirm_leave(self, confirmed: bool | None) -> None:
        if confirmed:
            self.app.pop_screen()
