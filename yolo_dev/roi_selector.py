"""Tk image-local selector, independent of OpenCV's Cocoa mouse callbacks."""

import tkinter as tk
from tkinter import ttk


def choose_crop(frame, validate, map_region):
    from PIL import Image, ImageTk

    height, width = frame.shape[:2]
    root = tk.Tk()
    root.title("Unity Game View crop")
    root.resizable(False, False)
    scale = min(1.0, min(1200, root.winfo_screenwidth()-100)/width,
                min(750, root.winfo_screenheight()-220)/height)
    pw, ph = max(1, round(width*scale)), max(1, round(height*scale))
    image = Image.fromarray(frame[:, :, ::-1]).resize((pw, ph), Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(image, master=root)
    ttk.Label(root, text=f"Image: {width} x {height} pixels. Drag the gameplay area, or enter image-local pixel coordinates.").pack(padx=12, pady=8)
    canvas = tk.Canvas(root, width=pw, height=ph, highlightthickness=0, cursor="crosshair")
    canvas.pack(padx=12)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    rectangle = canvas.create_rectangle(0, 0, 0, 0, outline="#00cfff", width=2)
    fields = ttk.Frame(root)
    fields.pack(padx=12, pady=10)
    values = []
    for label in ("X", "Y", "Width", "Height"):
        ttk.Label(fields, text=label).pack(side="left", padx=(8, 3))
        value = tk.StringVar(master=root, value="0")
        ttk.Entry(fields, textvariable=value, width=9).pack(side="left")
        values.append(value)
    message = tk.StringVar(master=root, value="Coordinates are relative to the captured image, not the desktop.")
    ttk.Label(root, textvariable=message, wraplength=pw).pack(padx=12, pady=4)
    result = None
    start = None

    def point(event):
        return max(0, min(pw, int(canvas.canvasx(event.x)))), max(0, min(ph, int(canvas.canvasy(event.y))))

    def press(event):
        nonlocal start
        start = point(event)
        canvas.coords(rectangle, *start, *start)

    def drag(event):
        if start is None:
            return
        x, y = point(event)
        left, top = min(start[0], x), min(start[1], y)
        right, bottom = max(start[0], x), max(start[1], y)
        canvas.coords(rectangle, left, top, right, bottom)
        if right > left and bottom > top:
            crop = map_region((left, top, right-left, bottom-top), pw, ph, width, height)
            for value, coordinate in zip(values, crop):
                value.set(str(coordinate))

    def confirm(_event=None):
        nonlocal result
        try:
            crop = tuple(int(value.get()) for value in values)
            result = validate(crop, width, height)
        except (ValueError, RuntimeError) as error:
            message.set(str(error))
            return
        root.destroy()

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", drag)
    buttons = ttk.Frame(root)
    buttons.pack(pady=10)
    ttk.Button(buttons, text="Use Crop", command=confirm).pack(side="left", padx=6)
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="left", padx=6)
    root.bind("<Return>", confirm)
    root.bind("<Escape>", lambda _event: root.destroy())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    print(f"Tk selector preview: {pw}x{ph}; captured image: {width}x{height}")
    try:
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    return result
