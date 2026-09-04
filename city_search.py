"""Non-blocking location suggestions for the existing Tk city field."""

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable


class CitySearch(tk.Frame):
    LIMIT = 5
    DEBOUNCE_MS = 300

    def __init__(
        self, parent, entry, variable, search_button, *, search: Callable,
        submit: Callable, dispatch: Callable, start_worker: Callable,
        font: tuple, background: str, max_query_length: int,
    ) -> None:
        super().__init__(parent, bg=background, bd=1, relief="solid")
        self.entry = entry
        self.variable = variable
        self.search_button = search_button
        self.search = search
        self.submit = submit
        self.dispatch = dispatch
        self.start_worker = start_worker
        self.max_query_length = max_query_length
        self.rows: list[dict] = []
        self.query = ""
        self.generation = 0
        self.inflight = False
        self.ready = False
        self.complete = False
        self.confirm_pending = False
        self.editing = False
        self.chosen_place: dict | None = None
        self.debounce_job = None
        self.focus_job = None
        self.closed = False
        self._setting_text = False
        self.listbox = tk.Listbox(
            self, font=font, bg=background, fg="#EAF0FF",
            selectbackground="#2B677E", selectforeground="#FFFFFF",
            activestyle="none", exportselection=False, takefocus=False,
            highlightthickness=0, bd=0, height=self.LIMIT,
        )
        self.message = tk.Label(
            self, font=font, bg=background, fg="#B6D0DE", anchor="w", padx=8, pady=6,
        )
        self.row_font = tkfont.Font(self, font=font)
        self.trace_id = variable.trace_add("write", self._changed)
        entry.bind("<Return>", self.confirm)
        entry.bind("<KP_Enter>", self.confirm)
        entry.bind("<Down>", lambda event: self._move(1))
        entry.bind("<Up>", lambda event: self._move(-1))
        entry.bind("<Escape>", self._escape)
        entry.bind("<FocusOut>", self._focus_out)
        self.listbox.bind("<Button-1>", self._click)
        self.listbox.bind("<Motion>", self._hover)
        self.popup = parent.winfo_toplevel()
        self.click_binding = self.popup.bind("<Button-1>", self._outside_click, add="+")
        self.focus_binding = self.popup.bind("<FocusOut>", self._focus_out, add="+")

    def _text(self) -> str:
        return " ".join(self.variable.get().split())

    def _cancel_debounce(self) -> None:
        if self.debounce_job is not None:
            self.after_cancel(self.debounce_job)
            self.debounce_job = None

    def dismiss(self) -> None:
        self._cancel_debounce()
        self.generation += 1
        self.ready = False
        self.confirm_pending = False
        self.rows = []
        self.complete = False
        self.listbox.delete(0, "end")
        self.listbox.pack_forget()
        self.message.pack_forget()
        self.place_forget()

    def hide(self) -> None:
        if self.confirm_pending:
            self.message.pack_forget()
            self.place_forget()
        else:
            self.dismiss()

    def set_text(self, text: str, place: dict | None = None) -> None:
        self.dismiss()
        self.editing = False
        self._setting_text = True
        try:
            self.variable.set(text)
        finally:
            self._setting_text = False
        self.chosen_place = place

    def _changed(self, *_args) -> None:
        if self.closed or self._setting_text:
            return
        self.editing = True
        self.dismiss()
        self.chosen_place = None
        self.query = self._text()
        if not 2 <= len(self.query) <= self.max_query_length:
            return
        self._show_message("Haetaan paikkakuntia...")
        self.debounce_job = self.after(self.DEBOUNCE_MS, self._request)

    def _request(self) -> None:
        self._cancel_debounce()
        self.ready = True
        if self.inflight or self.closed:
            return
        self.inflight = True
        generation, query = self.generation, self.query

        def worker() -> None:
            try:
                rows, error = self.search(query), False
            except Exception:  # Suggestions must never interrupt the weather view.
                rows, error = [], True
            self.dispatch(lambda: self._receive(generation, rows, error))

        try:
            self.start_worker(worker)
        except RuntimeError:
            self._receive(generation, [], True)

    def _receive(self, generation: int, rows: list[dict], error: bool) -> None:
        self.inflight = False
        if self.closed:
            return
        if generation != self.generation:
            if self.ready:
                self._request()
            return
        self.ready = False
        self.complete = True
        self.rows = rows[:self.LIMIT]
        if self.confirm_pending:
            self.confirm()
        elif self.rows:
            self.message.pack_forget()
            self.listbox.configure(height=len(self.rows))
            self.listbox.pack(fill="both", expand=True, padx=4, pady=4)
            self.reposition()
            self._select(0)
        else:
            self._show_message("Ehdotuksia ei voitu hakea" if error else "Ei löytyviä paikkakuntia")

    def confirm(self, _event=None) -> str:
        query = self._text()
        if self.chosen_place is not None:
            place = self.chosen_place
        elif query == self.query and self.rows:
            selection = self.listbox.curselection()
            place = self.rows[selection[0] if selection else 0]
        elif 2 <= len(query) <= self.max_query_length and not (query == self.query and self.complete):
            if query != self.query:
                self.dismiss()
                self.query = query
            self.confirm_pending = True
            self._finish_editing()
            self._show_message("Haetaan paikkakuntia...")
            self._request()
            return "break"
        else:
            place = None
        if place is not None:
            query = place["name"]
            self.set_text(query, place)
        else:
            self.dismiss()
            self.editing = False
        self._finish_editing()
        self.submit(query, place)
        return "break"

    def _finish_editing(self) -> None:
        self.entry.selection_clear()
        if self.focus_get() in (self.entry, self.listbox, self.search_button):
            self.master.focus_set()

    def _show_message(self, text: str) -> None:
        self.listbox.pack_forget()
        self.message.configure(text=text)
        self.message.pack(fill="x")
        self.reposition()

    @staticmethod
    def _label(place: dict) -> str:
        parts = []
        for key in ("name", "admin1", "country"):
            text = place.get(key, "")
            if text and text not in parts:
                parts.append(text)
        return ", ".join(parts)

    def reposition(self) -> None:
        if self.closed or not (self.rows or self.message.winfo_manager()):
            return
        parent = self.master
        width = max(1, min(380, parent.winfo_width() - 20))
        right = self.entry.winfo_rootx() - parent.winfo_rootx() + self.entry.winfo_width() + 5
        x = max(10, min(right - width, parent.winfo_width() - width - 10))
        y = self.entry.winfo_rooty() - parent.winfo_rooty() + self.entry.winfo_height() + 3
        self.place(x=x, y=y, width=width)
        self.lift()
        selection = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for place in self.rows:
            label = self._label(place)
            if self.row_font.measure(label) > width - 18:
                while label and self.row_font.measure(label + "...") > width - 18:
                    label = label[:-1]
                label += "..."
            self.listbox.insert("end", label)
        if self.rows:
            self._select(min(selection[0] if selection else 0, len(self.rows) - 1))

    def _select(self, index: int) -> None:
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)

    def _move(self, direction: int) -> str:
        if self.rows:
            selection = self.listbox.curselection()
            index = selection[0] if selection else 0
            self._select(max(0, min(len(self.rows) - 1, index + direction)))
        elif not self.inflight and not self.debounce_job:
            self._changed()
        return "break"

    def _hover(self, event) -> None:
        if self.rows:
            self._select(self.listbox.nearest(event.y))

    def _click(self, event) -> str:
        if self.rows:
            self._hover(event)
            self.confirm()
        return "break"

    def _escape(self, _event=None):
        if self.winfo_manager() or self.confirm_pending:
            self.dismiss()
            return "break"
        return None

    def _outside_click(self, event) -> None:
        if event.widget not in (self.entry, self.listbox, self.search_button):
            self.hide()

    def _focus_out(self, _event=None) -> None:
        if self.focus_job is None and not self.closed:
            self.focus_job = self.after_idle(self._check_focus)

    def _check_focus(self) -> None:
        self.focus_job = None
        focused = self.focus_get()
        # A confirmed search survives switching windows or hiding the card.
        if self.confirm_pending and focused == self.master:
            return
        if focused not in (self.entry, self.listbox, self.search_button):
            self.hide()

    def destroy(self) -> None:
        self.closed = True
        self.dismiss()
        if self.focus_job is not None:
            self.after_cancel(self.focus_job)
        self.variable.trace_remove("write", self.trace_id)
        self.popup.unbind("<Button-1>", self.click_binding)
        self.popup.unbind("<FocusOut>", self.focus_binding)
        super().destroy()
