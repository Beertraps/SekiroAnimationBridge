"""Source spaces: a game's axis convention and unit, and their conversion to Blender's space.

A basis is a signed permutation matrix B, written as three rows, that maps a source vector to Blender:
v_blender = unit * B * v_source. See docs/INTERCHANGE.md. This module has no dependencies, so the bridge,
Blender's Python and the tests all use the same conversion.
"""
from __future__ import annotations

# Havok and FLVER: Y up, left-handed. Swapping Y and Z reflects.
FROMSOFT_BASIS = ((1, 0, 0), (0, 0, 1), (0, 1, 0))
# RE Engine: Y up, right-handed. +90 degrees about X.
RE_ENGINE_BASIS = ((1, 0, 0), (0, 0, -1), (0, 1, 0))


class Space:
    """The conversion between one source space and Blender's."""
    __slots__ = ('basis', 'unit', 'indices', 'signs', 'determinant')

    def __init__(self, basis=FROMSOFT_BASIS, unit=1.0):
        rows = tuple(tuple(float(value) for value in row) for row in basis)
        if len(rows) != 3 or any(len(row) != 3 for row in rows):
            raise ValueError('A basis has three rows of three numbers.')
        indices, signs = [], []
        for row in rows:
            nonzero = [column for column, value in enumerate(row) if value != 0]
            if len(nonzero) != 1 or abs(row[nonzero[0]]) != 1:
                raise ValueError('A basis must be a signed permutation: one 1 or -1 in each row and column.')
            indices.append(nonzero[0])
            signs.append(row[nonzero[0]])
        if sorted(indices) != [0, 1, 2]:
            raise ValueError('A basis must be a signed permutation: one 1 or -1 in each row and column.')
        unit = float(unit)
        if not unit > 0:
            raise ValueError('The unit scale must be positive.')
        # The determinant of a signed permutation: the permutation's parity times the signs.
        parity = 1.0
        for i in range(3):
            for j in range(i + 1, 3):
                if indices[i] > indices[j]:
                    parity = -parity
        self.basis, self.unit = rows, unit
        self.indices, self.signs = tuple(indices), tuple(signs)
        self.determinant = parity * signs[0] * signs[1] * signs[2]

    @classmethod
    def of(cls, document):
        """The space a motion JSON, manifest or preview document declares; the FromSoftware space without one."""
        document = document or {}
        return cls(document.get('basis') or FROMSOFT_BASIS, document.get('unitScale', 1.0))

    @property
    def reflects(self):
        """True when the conversion mirrors, so triangles need their winding reversed."""
        return self.determinant < 0

    def to_json(self):
        return dict(basis=[[int(value) for value in row] for row in self.basis], unitScale=self.unit)

    def __eq__(self, other):
        return isinstance(other, Space) and self.basis == other.basis and self.unit == other.unit

    def __hash__(self):
        return hash((self.basis, self.unit))

    def __repr__(self):
        return f'Space({self.to_json()["basis"]}, {self.unit:g})'

    # Source to Blender.
    def vector(self, v):
        """A direction such as a normal: B * v."""
        return tuple(float(v[i]) * s for i, s in zip(self.indices, self.signs))

    def point(self, v):
        """A position or translation: unit * B * v."""
        return tuple(float(v[i]) * s * self.unit for i, s in zip(self.indices, self.signs))

    def scale(self, v):
        """A scale: its components reordered like B, without signs."""
        return tuple(float(v[i]) for i in self.indices)

    def quaternion(self, xyzw):
        """A rotation [x, y, z, w] as Blender's (w, x, y, z): w unchanged, xyz becomes det(B) * B * xyz."""
        x, y, z, w = (float(value) for value in xyzw)
        vector = self.vector((x, y, z))
        return (w, *(value * self.determinant for value in vector))

    # Blender to source.
    def inverse_vector(self, v):
        result = [0.0, 0.0, 0.0]
        for row, (i, s) in enumerate(zip(self.indices, self.signs)):
            result[i] = float(v[row]) * s
        return tuple(result)

    def inverse_point(self, v):
        return tuple(value / self.unit for value in self.inverse_vector(v))

    def inverse_scale(self, v):
        result = [0.0, 0.0, 0.0]
        for row, i in enumerate(self.indices):
            result[i] = float(v[row])
        return tuple(result)

    def inverse_quaternion(self, wxyz):
        """Blender's (w, x, y, z) as a source rotation [x, y, z, w]."""
        w, x, y, z = (float(value) for value in wxyz)
        vector = self.inverse_vector((x, y, z))
        return [*(value * self.determinant for value in vector), w]

    def yaw(self, angle):
        """A turn about the source's up axis (Y) as a turn about Blender's Z, for root motion."""
        up = self.vector((0.0, 1.0, 0.0))
        if not up[2]:
            raise ValueError('Root motion turns about the source up axis, Y, which this basis does not map to Blender Z.')
        return float(angle) * up[2] * self.determinant

    def inverse_yaw(self, angle):
        """A turn about Blender's Z as a turn about the source's up axis. The factor is 1 or -1, its own inverse."""
        return self.yaw(angle)

    def matrix(self):
        """C = unit * B as a 4x4 matrix: C * M * C^-1 converts a source transform matrix M."""
        rows = [[value * self.unit for value in row] + [0.0] for row in self.basis]
        return [*rows, [0.0, 0.0, 0.0, 1.0]]

    def inverse_matrix(self):
        """C^-1 = B^T / unit as a 4x4 matrix."""
        rows = [[self.basis[column][row] / self.unit for column in range(3)] + [0.0] for row in range(3)]
        return [*rows, [0.0, 0.0, 0.0, 1.0]]


FROMSOFT = Space(FROMSOFT_BASIS)
RE_ENGINE = Space(RE_ENGINE_BASIS)
