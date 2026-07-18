"""ToneEditorScreen: tweak the params of blocks already in a tone's chain.

Opened with Enter on a Library tone. Left pane lists every block (grouped by
lane); right pane lists the selected block's params. Left/right nudges the
selected param (float 0.01 clamped to [0,1]; int +/-1; bool toggles); Enter
opens inline manual entry. Edits are held in a working set and written to the
library ``.hsp`` only on an explicit ``s``/``ctrl+s`` — never autosaved, never
pushed to the device. A dirty indicator shows while there are unsaved edits and
a confirm guards leaving with them.

Scope is param editing only: adding/removing/reordering blocks and editing
splits/parallel paths is out of scope for v1 (backlog #13).

Markup safety (repo bug class #12): the header is a ``markup=False`` Static and
every DataTable cell is a ``rich.text.Text`` so a bracket-bearing model or param
name renders literally instead of being stripped / crashing the screen.
"""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from helixgen_tui.core.models import BlockVM, ChainVM, MutationPlan, OpResult, ParamChange, ParamVM
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter

_BLOCKS_ID = "editor-blocks"
_PARAMS_ID = "editor-params"
_HEADER_ID = "editor-header"
_ENTRY_ID = "editor-entry"

_FLOAT_STEP = 0.01

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
    """Full-screen param editor for one tone's chain."""

    DEFAULT_CSS = f"""
    ToneEditorScreen #{_HEADER_ID} {{
        height: 4;
        padding: 0 1;
        background: $panel;
        color: $text;
    }}

    ToneEditorScreen Horizontal {{
        height: 1fr;
    }}

    ToneEditorScreen #{_BLOCKS_ID} {{
        width: 1fr;
        height: 100%;
    }}

    ToneEditorScreen #{_PARAMS_ID} {{
        width: 2fr;
        height: 100%;
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
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("left", "nudge(-1)", "Nudge -", show=False),
        Binding("right", "nudge(1)", "Nudge +", show=False),
        Binding("enter", "manual_entry", "Edit value"),
        Binding("s", "save", "Save"),
        Binding("ctrl+s", "save", "Save", show=False),
        Binding("escape", "leave", "Back"),
    ]

    def __init__(self, tone_id: str) -> None:
        self._tone_id = tone_id
        self._chain: ChainVM | None = None
        # Flattened (path, block) rows in the left pane's display order.
        self._blocks: list[BlockVM] = []
        self._block_index = 0
        self._param_index = 0
        # Working edits: (model, path, position, param) -> new value. Present
        # only while the value differs from disk (an edit back to the on-disk
        # value prunes itself), so ``bool(self._edits)`` is the dirty flag.
        self._edits: dict[tuple[str, int, int, str], object] = {}
        self._editing = False
        self._focus = "blocks"
        super().__init__()

    # -- compose -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id=_HEADER_ID, markup=False)
        blocks = DataTable(id=_BLOCKS_ID, cursor_type="row")
        params = DataTable(id=_PARAMS_ID, cursor_type="row")
        # Non-focusable so the screen's own bindings own every nav/edit key;
        # a focused DataTable would swallow up/down/left/right/enter/tab.
        blocks.can_focus = False
        params.can_focus = False
        with Horizontal():
            yield blocks
            yield params
        with Vertical(id="bottom-bars"):
            yield StatusFooter()
            yield Footer()

    def on_mount(self) -> None:
        blocks = self.query_one(f"#{_BLOCKS_ID}", DataTable)
        params = self.query_one(f"#{_PARAMS_ID}", DataTable)
        blocks.add_columns("Path", "Block", "Pos", "State")
        params.add_columns("Param", "Value")
        # Belt-and-suspenders: ensure nothing holds focus so keys reach us.
        self.set_focus(None)

        footer = self.query_one(StatusFooter)
        footer.set_device_text(self.app.device_text)

        self._chain = self.app.core.editor.get_chain(self._tone_id)
        self._flatten_blocks()
        self._render_header()
        self._rebuild_blocks_table()
        self._rebuild_params_table()
        self._reflect_focus()

    # -- data shaping ------------------------------------------------------

    def _flatten_blocks(self) -> None:
        self._blocks = []
        if self._chain is None:
            return
        for path in self._chain.paths:
            for block in path.blocks:
                self._blocks.append(block)

    def _selected_block(self) -> BlockVM | None:
        if not self._blocks:
            return None
        self._block_index = max(0, min(self._block_index, len(self._blocks) - 1))
        return self._blocks[self._block_index]

    def _selected_params(self) -> list[ParamVM]:
        block = self._selected_block()
        return list(block.params) if block is not None else []

    def _selected_param(self) -> ParamVM | None:
        params = self._selected_params()
        if not params:
            return None
        self._param_index = max(0, min(self._param_index, len(params) - 1))
        return params[self._param_index]

    def _current_value(self, block: BlockVM, param: ParamVM) -> object:
        """The working value: a pending edit if present, else the on-disk value."""
        key = (block.model, block.path, block.position, param.name)
        return self._edits.get(key, param.value)

    @property
    def is_dirty(self) -> bool:
        return bool(self._edits)

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

    def _rebuild_blocks_table(self) -> None:
        table = self.query_one(f"#{_BLOCKS_ID}", DataTable)
        table.clear()
        for block in self._blocks:
            state = "on" if block.enabled else "bypassed"
            table.add_row(
                Text(str(block.path)),
                Text(block.display),
                Text(str(block.position)),
                Text(state),
            )
        if self._blocks:
            table.move_cursor(row=min(self._block_index, len(self._blocks) - 1))

    def _rebuild_params_table(self) -> None:
        table = self.query_one(f"#{_PARAMS_ID}", DataTable)
        table.clear()
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
        # A visible cue for which pane is active: border the active table.
        blocks = self.query_one(f"#{_BLOCKS_ID}", DataTable)
        params = self.query_one(f"#{_PARAMS_ID}", DataTable)
        blocks.set_class(self._focus == "blocks", "-active-pane")
        params.set_class(self._focus == "params", "-active-pane")

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def _move_cursor(self, delta: int) -> None:
        if self._editing:
            return
        if self._focus == "blocks":
            if not self._blocks:
                return
            self._block_index = max(0, min(self._block_index + delta, len(self._blocks) - 1))
            self._param_index = 0
            self._rebuild_blocks_table()
            self._rebuild_params_table()
        else:
            params = self._selected_params()
            if not params:
                return
            self._param_index = max(0, min(self._param_index + delta, len(params) - 1))
            self.query_one(f"#{_PARAMS_ID}", DataTable).move_cursor(row=self._param_index)

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

    def action_nudge(self, direction: int) -> None:
        if self._editing or self._focus != "params":
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _ENTRY_ID:
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

    def _close_entry(self) -> None:
        self._editing = False
        try:
            self.query_one(f"#{_ENTRY_ID}", Input).remove()
        except Exception:  # noqa: BLE001 — already gone
            pass
        self._reflect_focus()

    # -- save / leave ------------------------------------------------------

    def _pending_changes(self) -> list[ParamChange]:
        return [
            ParamChange(model=model, path=path, position=position, param=param, value=value)
            for (model, path, position, param), value in self._edits.items()
        ]

    def action_save(self) -> None:
        if self._editing:
            return
        if not self._edits:
            self.app.report_op(OpResult(ok=True, message="nothing to save"))
            return
        changes = self._pending_changes()
        result = self.app.core.editor.save_params(self._tone_id, changes)
        self.app.report_op(result)
        if result.ok:
            # Rebase to the saved values so the display stays and dirty clears.
            self._edits.clear()
            self._chain = self.app.core.editor.get_chain(self._tone_id)
            self._flatten_blocks()
            self._render_header()
            self._rebuild_blocks_table()
            self._rebuild_params_table()

    def action_leave(self) -> None:
        if self._editing:
            self._close_entry()
            return
        if not self._edits:
            self.app.pop_screen()
            return
        plan = MutationPlan(
            title="Discard unsaved changes?",
            lines=(f"{len(self._edits)} unsaved param edit(s) will be lost.",),
        )
        self.app.push_screen(ConfirmModal(plan), self._confirm_leave)

    def _confirm_leave(self, confirmed: bool | None) -> None:
        if confirmed:
            self.app.pop_screen()
