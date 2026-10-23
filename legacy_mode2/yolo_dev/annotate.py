"""Local XBot head annotation UI. Uses existing Tkinter/Pillow dependencies."""

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

if __package__:
    from .annotation_data import AnnotationStore
else:
    from annotation_data import AnnotationStore

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "datasets" / "xbot_head"


class Annotator:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.index = 0
        self.boxes = []
        self.history = []
        self.selected = None
        self.start = self.draft = None
        self.image = self.photo = None
        self.mode = tk.StringVar(value="draw")
        self.reviewed = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.title = tk.StringVar()
        root.title("XBot Head Annotator")
        root.geometry("1100x780")
        root.minsize(760, 520)
        root.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(root, padding=10)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Previous", command=lambda: self.navigate(-1)).pack(side="left")
        ttk.Button(toolbar, text="Next", command=lambda: self.navigate(1)).pack(side="left", padx=5)
        ttk.Radiobutton(toolbar, text="Draw", variable=self.mode, value="draw").pack(side="left", padx=(15, 5))
        ttk.Radiobutton(toolbar, text="Select", variable=self.mode, value="select").pack(side="left")
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side="left", padx=(15, 5))
        ttk.Button(toolbar, text="Delete Box", command=self.delete).pack(side="left")
        ttk.Button(toolbar, text="Export 80/20", command=self.export).pack(side="right")
        ttk.Label(root, textvariable=self.title, padding=(10, 4)).pack(fill="x")
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=10)
        sidebar = ttk.Frame(body, width=180)
        sidebar.pack(side="right", fill="y", padx=(10, 0))
        ttk.Label(sidebar, text="0 - xbot_head").pack(anchor="w", pady=5)
        self.box_list = tk.Listbox(sidebar, width=23, exportselection=False)
        self.box_list.pack(fill="both", expand=True)
        self.box_list.bind("<<ListboxSelect>>", self.select_list)
        self.canvas = tk.Canvas(body, background="#20242a", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.render())
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        footer = ttk.Frame(root, padding=10)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        ttk.Checkbutton(footer, text="Reviewed", variable=self.reviewed, command=self.save).pack(side="right", padx=10)
        ttk.Button(footer, text="Reviewed + Next", command=self.review_next).pack(side="right")
        for key in ("<Control-z>", "<Command-z>"):
            root.bind(key, lambda _event: self.undo())
        for key in ("<Delete>", "<BackSpace>"):
            root.bind(key, lambda _event: self.delete())
        root.bind("<Left>", lambda _event: self.navigate(-1))
        root.bind("<Right>", lambda _event: self.navigate(1))
        root.bind("<Control-s>", lambda _event: self.save())
        root.bind("<Command-s>", lambda _event: self.save())
        self.load(0)
        if self.image is None:
            root.after_idle(root.destroy)

    @property
    def path(self):
        return self.store.images[self.index]

    def load(self, index):
        path = self.store.images[index]
        try:
            boxes = self.store.load(path)
            with Image.open(path) as source:
                image = source.convert("RGB")
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot load annotation", str(error), parent=self.root)
            return
        self.index, self.boxes, self.image = index, boxes, image
        self.reviewed.set(self.store.reviewed(path))
        self.selected = self.start = self.draft = None
        self.history.clear()
        self.refresh_list()
        self.render()
        self.update_status()

    def update_status(self):
        count = sum(bool(self.store.reviewed(image)) for image in self.store.images)
        self.title.set(f"{self.index+1} / {len(self.store.images)}   {self.path.name}   {self.image.width} x {self.image.height}")
        self.status.set(f"{len(self.boxes)} boxes | {count}/{len(self.store.images)} reviewed | Autosave")

    def save(self):
        if self.image is None:
            return False
        try:
            self.store.save(self.path, self.boxes, self.reviewed.get())
        except (OSError, ValueError) as error:
            messagebox.showerror("Autosave failed", str(error), parent=self.root)
            return False
        self.update_status()
        return True

    def snapshot(self):
        self.history.append((self.boxes.copy(), self.reviewed.get()))

    def changed(self):
        self.reviewed.set(False)
        self.refresh_list()
        self.render()
        self.save()

    def refresh_list(self):
        self.box_list.delete(0, "end")
        for index, (x1, y1, x2, y2) in enumerate(self.boxes):
            self.box_list.insert("end", f"Head {index+1}   {round(x2-x1)} x {round(y2-y1)}")
        if self.selected is not None and self.selected < len(self.boxes):
            self.box_list.selection_set(self.selected)

    def render(self):
        if self.image is None:
            return
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(cw/self.image.width, ch/self.image.height)
        dw, dh = max(1, round(self.image.width*scale)), max(1, round(self.image.height*scale))
        self.sx, self.sy = dw/self.image.width, dh/self.image.height
        self.ox, self.oy = (cw-dw)/2, (ch-dh)/2
        self.photo = ImageTk.PhotoImage(self.image.resize((dw, dh), Image.Resampling.LANCZOS), master=self.root)
        self.canvas.delete("all")
        self.canvas.create_image(self.ox, self.oy, image=self.photo, anchor="nw")
        self.draft = None
        for index, (x1, y1, x2, y2) in enumerate(self.boxes):
            color = "#ffcc55" if index == self.selected else "#40e4ac"
            self.canvas.create_rectangle(self.ox+x1*self.sx, self.oy+y1*self.sy, self.ox+x2*self.sx,
                                         self.oy+y2*self.sy, outline=color, width=2)
            self.canvas.create_text(self.ox+x1*self.sx+3, self.oy+y1*self.sy+3, anchor="nw",
                                    text=f"{index+1}: xbot_head", fill=color)

    def point(self, event, clamp=False):
        x, y = (event.x-self.ox)/self.sx, (event.y-self.oy)/self.sy
        if not clamp and not (0 <= x <= self.image.width and 0 <= y <= self.image.height):
            return None
        return max(0, min(self.image.width, x)), max(0, min(self.image.height, y))

    def press(self, event):
        self.canvas.focus_set()
        point = self.point(event)
        if point is None:
            return
        if self.mode.get() == "select":
            x, y = point
            candidates = [i for i, (a,b,c,d) in enumerate(self.boxes) if a <= x <= c and b <= y <= d]
            self.selected = min(candidates, key=lambda i: (self.boxes[i][2]-self.boxes[i][0])*(self.boxes[i][3]-self.boxes[i][1])) if candidates else None
            self.refresh_list()
            self.render()
        else:
            self.start = point

    def drag(self, event):
        if self.start is None:
            return
        x, y = self.point(event, clamp=True)
        a, b = self.start
        if self.draft is not None:
            self.canvas.delete(self.draft)
        self.draft = self.canvas.create_rectangle(self.ox+a*self.sx, self.oy+b*self.sy,
                                                  self.ox+x*self.sx, self.oy+y*self.sy,
                                                  outline="#58cfff", width=2)

    def release(self, event):
        if self.start is None:
            return
        a, b = self.start
        x, y = self.point(event, clamp=True)
        self.start = None
        box = min(a,x), min(b,y), max(a,x), max(b,y)
        if box[2]-box[0] < 2 or box[3]-box[1] < 2:
            self.render()
            return
        self.snapshot()
        self.boxes.append(box)
        self.selected = len(self.boxes)-1
        self.changed()

    def select_list(self, _event=None):
        selected = self.box_list.curselection()
        if selected:
            self.selected = selected[0]
            self.render()

    def delete(self):
        if self.selected is None:
            return
        self.snapshot()
        del self.boxes[self.selected]
        self.selected = None
        self.changed()

    def undo(self):
        if not self.history:
            return
        self.boxes, reviewed = self.history.pop()
        self.reviewed.set(reviewed)
        self.selected = None
        self.refresh_list()
        self.render()
        self.save()

    def navigate(self, direction):
        index = max(0, min(len(self.store.images)-1, self.index+direction))
        if index != self.index and self.save():
            self.load(index)

    def review_next(self):
        self.reviewed.set(True)
        if self.save():
            self.navigate(1)

    def export(self):
        if not self.save():
            return
        if not messagebox.askyesno("Export dataset", "Export reviewed image/label pairs as 80% train / 20% validation? Previous split folders will be backed up locally.", parent=self.root):
            return
        try:
            result = self.store.export()
        except (OSError, ValueError) as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)
            return
        messagebox.showinfo("Dataset exported", f"Train: {result['train']}\nValidation: {result['val']}\n" + result["warning"], parent=self.root)

    def close(self):
        if self.save():
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    try:
        store = AnnotationStore(args.dataset)
        if not store.images:
            raise ValueError(f"No PNG/JPG dataset images found in {store.raw}; metadata and previews are skipped.")
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    root = tk.Tk()
    Annotator(root, store)
    root.mainloop()


if __name__ == "__main__":
    main()
