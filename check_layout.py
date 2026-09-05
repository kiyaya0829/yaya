"""Exercise actual Tk geometry at small sizes and high DPI on Windows CI."""
from pathlib import Path
import tempfile
import tkinter as tk
from app import App
from journal import Journal


def check():
    for scaling in (1.0, 1.5, 2.0, 2.5):
        for width, height in ((640, 480), (1120, 760), (1600, 900)):
            with tempfile.TemporaryDirectory() as tmp:
                root = tk.Tk()
                root.tk.call('tk', 'scaling', scaling)
                app = App(root, Journal(Path(tmp) / 'layout.sqlite3'), auto_update=False)
                root.geometry(f'{width}x{height}+0+0')
                root.update()
                button = app.save_button
                assert button.winfo_ismapped(), (scaling, width, height, 'save not mapped')
                x = button.winfo_rootx() - root.winfo_rootx()
                y = button.winfo_rooty() - root.winfo_rooty()
                assert x >= 0 and x + button.winfo_width() <= root.winfo_width()
                assert y >= 0 and y + button.winfo_height() <= root.winfo_height()
                app.content_canvas.yview_moveto(1)
                root.update()
                note_bottom = app.note.winfo_rooty() + app.note.winfo_height()
                canvas_bottom = app.content_canvas.winfo_rooty() + app.content_canvas.winfo_height()
                assert note_bottom <= canvas_bottom, (scaling, width, height, 'note unreachable')
                app.fields['symbol'].set('TEST')
                app.fields['price'].set('10')
                app.fields['quantity'].set('1')
                button.invoke()
                assert len(app.journal.all()) == 1
                app.close()
    print('12 window/DPI combinations: save visible, notes reachable, save works')


if __name__ == '__main__':
    check()
