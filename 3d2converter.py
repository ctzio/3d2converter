"""Convert Atari ST CAD-3D 2.0 .3D2 files to binary STL."""

from __future__ import annotations

import math
import struct
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HEADER_SIZE = 256
FILE_ID = 0x3D02
MAX_OBJECTS = 40
MAX_VERTICES = 15000
MAX_FACES = 30000


class FormatError(ValueError):
    """Raised when a file does not conform to the CAD-3D 2.0 format."""


@dataclass
class Mesh:
    name: str
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]


class Reader:
    def __init__(self, data: bytes):
        self.data, self.offset = data, 0

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise FormatError(f"Unexpected end of file at byte {self.offset}.")
        result = self.data[self.offset:end]
        self.offset = end
        return result

    def word(self, signed=False) -> int:
        return struct.unpack(">h" if signed else ">H", self.take(2))[0]


def read_3d2(path: Path) -> list[Mesh]:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise FormatError("File is shorter than the 256-byte header.")
    reader = Reader(data)
    file_id = reader.word()
    if file_id != FILE_ID:
        raise FormatError(f"Invalid file ID 0x{file_id:04X}; expected 0x{FILE_ID:04X}.")
    object_count = reader.word()
    if not 1 <= object_count <= MAX_OBJECTS:
        raise FormatError(f"Object count {object_count} is outside 1–{MAX_OBJECTS}.")
    reader.take(HEADER_SIZE - 4)
    meshes = []
    for object_number in range(object_count):
        raw_name = reader.take(9)
        name = raw_name.split(b"\0", 1)[0].decode("latin-1", errors="replace").strip()
        name = name or f"Object_{object_number + 1}"
        vertex_count = reader.word()
        if vertex_count > MAX_VERTICES:
            raise FormatError(f"{name}: vertex count {vertex_count} is too large.")
        vertices = [(reader.word(True) / 100.0, reader.word(True) / 100.0, reader.word(True) / 100.0)
                    for _ in range(vertex_count)]
        face_count = reader.word()
        if face_count > MAX_FACES:
            raise FormatError(f"{name}: face count {face_count} is too large.")
        faces = []
        for face_number in range(face_count):
            a, b, c = reader.word(), reader.word(), reader.word()
            reader.word()  # color and edge flags are not needed by STL
            if max(a, b, c) >= vertex_count:
                raise FormatError(f"{name}: face {face_number + 1} references a missing vertex.")
            if len({a, b, c}) == 3:
                faces.append((a, b, c))
        meshes.append(Mesh(name, vertices, faces))
    return meshes


def triangle_normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (0.0, 0.0, 0.0) if length == 0 else (nx / length, ny / length, nz / length)


def write_stl(path: Path, meshes: list[Mesh], swap_yz=False) -> int:
    triangles = []
    for mesh in meshes:
        vertices = [(x, z, y) if swap_yz else (x, y, z) for x, y, z in mesh.vertices]
        triangles.extend((vertices[a], vertices[b], vertices[c]) for a, b, c in mesh.faces)
    header = ("Converted from Atari ST CAD-3D 2.0: " + path.stem)[:80].encode("ascii", "replace").ljust(80, b" ")
    with path.open("wb") as output:
        output.write(header)
        output.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            output.write(struct.pack("<3f", *triangle_normal(a, b, c)))
            output.write(struct.pack("<3f", *a))
            output.write(struct.pack("<3f", *b))
            output.write(struct.pack("<3f", *c))
            output.write(struct.pack("<H", 0))
    return len(triangles)


class ConverterApp:
    def __init__(self, root):
        self.root = root
        root.title("Atari ST CAD-3D 2.0 to STL Converter")
        root.minsize(650, 390)
        self.files = []
        self.output_dir = tk.StringVar(value=str(Path.cwd()))
        self.swap_yz = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Select one or more .3D2 files to begin.")
        self.build_ui()

    def build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Input files (.3D2)").pack(anchor="w")
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True, pady=(4, 8))
        self.file_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=10)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(0, 10))
        ttk.Button(buttons, text="Add files…", command=self.add_files).pack(side="left")
        ttk.Button(buttons, text="Remove selected", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(buttons, text="Clear", command=self.clear_files).pack(side="left")
        ttk.Label(frame, text="Output directory").pack(anchor="w")
        output_row = ttk.Frame(frame)
        output_row.pack(fill="x", pady=(4, 10))
        ttk.Entry(output_row, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="Choose…", command=self.choose_output).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(frame, text="Swap CAD-3D Y and Z axes", variable=self.swap_yz).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, wraplength=620).pack(anchor="w", pady=(12, 8))
        ttk.Button(frame, text="Convert to STL", command=self.convert).pack(anchor="e")

    def add_files(self):
        selected = filedialog.askopenfilenames(title="Select CAD-3D 2.0 files",
            filetypes=[("CAD-3D files", "*.3d2 *.3D2"), ("All files", "*.*")])
        for filename in selected:
            if filename not in self.files:
                self.files.append(filename)
                self.file_list.insert("end", filename)
        self.status.set(f"{len(self.files)} file(s) selected.")

    def remove_selected(self):
        for index in reversed(self.file_list.curselection()):
            self.file_list.delete(index)
            del self.files[index]
        self.status.set(f"{len(self.files)} file(s) selected.")

    def clear_files(self):
        self.files.clear()
        self.file_list.delete(0, "end")
        self.status.set("Select one or more .3D2 files to begin.")

    def choose_output(self):
        chosen = filedialog.askdirectory(title="Choose STL output directory", initialdir=self.output_dir.get())
        if chosen:
            self.output_dir.set(chosen)

    def convert(self):
        if not self.files:
            messagebox.showwarning("No input files", "Please select at least one .3D2 file.")
            return
        output_dir = Path(self.output_dir.get()).expanduser()
        if not output_dir.is_dir():
            messagebox.showerror("Invalid output directory", "Please choose an existing output directory.")
            return
        successes, errors = [], []
        for filename in self.files:
            source = Path(filename)
            try:
                meshes = read_3d2(source)
                destination = output_dir / f"{source.stem}.stl"
                count = write_stl(destination, meshes, self.swap_yz.get())
                successes.append(f"{source.name} → {destination.name} ({count} triangles)")
            except (OSError, FormatError, struct.error) as exc:
                errors.append(f"{source.name}: {exc}")
        self.status.set(f"Converted {len(successes)} of {len(self.files)} file(s).")
        details = "\n".join(successes)
        if errors:
            details += ("\n\nErrors:\n" if details else "Errors:\n") + "\n".join(errors)
            messagebox.showerror("Conversion completed with errors", details)
        else:
            messagebox.showinfo("Conversion complete", details)


def main():
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
