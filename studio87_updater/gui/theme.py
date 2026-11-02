"""One token table for the three suite looks. No literal colour anywhere else in the GUI."""
from PySide6.QtGui import QColor

LOOKS = {
    # Look A, Neon Navy
    "navy": dict(label="Neon Navy", bg="#161638", panel="#1c1c4a", panel2="#2C2C62", line="#4a4a8c", text="#e8e6e1", dim="#9a9690",
                 accent="#FFA600", good="#02EBBA", info="#6CC9F5", bad="#FF1383", title="#E1CBF4", display="#05060d",
                 btn="#2C2C62", btn_hot="#3a3a7c", primary="#FFA600", primary_text="#1b1204"),
    # Look B, Purple Soda Pop
    "soda": dict(label="Purple Soda Pop", bg="#0b0b0d", panel="#15161a", panel2="#1c1d22", line="#2b2d34", text="#f4f5f7", dim="#a9adb8",
                 accent="#FFD100", good="#02EBBA", info="#A43DFF", bad="#FF1383", title="#E1CBF4", display="#06080a",
                 btn="#241238", btn_hot="#341a52", primary="#A43DFF", primary_text="#ffffff"),
    # Look C, PurrOne
    "purr": dict(label="PurrOne", bg="#17181b", panel="#202125", panel2="#2a2b30", line="#3a3b41", text="#ffffff", dim="#9c9ea6",
                 accent="#FFD100", good="#02EBBA", info="#6CC9F5", bad="#FF1383", title="#ffffff", display="#0b0c0e",
                 btn="#2f3036", btn_hot="#3d3e46", primary="#02EBBA", primary_text="#04201a"),
}
# The PurrOne wood is the same in every look.
WOOD = dict(dark="#3d2210", warm="#7b4a26", mid="#5a3419")


class Theme:
    def __init__(self, name="purr"):
        self.set(name)

    def set(self, name):
        self.name = name if name in LOOKS else "purr"
        self.t = LOOKS[self.name]

    def c(self, key):
        return QColor(self.t[key])

    def s(self, key):
        return self.t[key]


THEME = Theme()
