import cv2
import numpy as np
from scipy import ndimage

from .utils import ind2sub, StructureRecognitionModule
from .widgets import Section, line_edit_template, combo_box_template


def polar_bins(shape, inner, outer, nbins_angular=32, nbins_radial=None):
    if nbins_radial is None:
        nbins_radial = outer - inner

    sx, sy = shape
    X, Y = np.ogrid[0:sx, 0:sy]

    r = np.hypot(X - sx / 2, Y - sy / 2)
    radial_bins = -np.ones(shape, dtype=int)
    valid = (r > inner) & (r < outer)
    radial_bins[valid] = nbins_radial * (r[valid] - inner) / (outer - inner)

    angles = np.arctan2(X - sx // 2, Y - sy // 2) % (2 * np.pi)

    angular_bins = np.floor(nbins_angular * (angles / (2 * np.pi)))
    angular_bins = np.clip(angular_bins, 0, nbins_angular - 1).astype(np.int)

    bins = -np.ones(shape, dtype=int)
    bins[valid] = angular_bins[valid] * nbins_radial + radial_bins[valid]
    return bins


def unroll_powerspec(f, inner=1, outer=None, nbins_angular=64, nbins_radial=None):
    if f.shape[0] != f.shape[1]:
        raise RuntimeError()

    if outer is None:
        outer = min(f.shape) // 2

    if nbins_radial is None:
        nbins_radial = outer - inner

    bins = polar_bins(f.shape, inner, outer, nbins_angular=nbins_angular, nbins_radial=nbins_radial)

    with np.errstate(divide='ignore', invalid='ignore'):
        unrolled = ndimage.mean(f, bins, range(0, bins.max() + 1))

    unrolled = unrolled.reshape((nbins_angular, nbins_radial))

    for i in range(unrolled.shape[1]):
        y = unrolled[:, i]
        nans = np.isnan(y)
        y[nans] = np.interp(nans.nonzero()[0], (~nans).nonzero()[0], y[~nans], period=len(y))
        unrolled[:, i] = y

    return unrolled


def make_circular_template(angles, nbins_angular=64, gauss_width=1., margin=1):
    angles = np.array(angles) * nbins_angular / (2 * np.pi) + margin
    x, y = np.mgrid[:nbins_angular + 2 * margin, -margin:margin + 1]
    r2 = (x[None] - angles[:, None, None]) ** 2 + y ** 2
    template = np.exp(-r2 / (2 * gauss_width ** 2)).sum(axis=0)

    template[margin:2 * margin] += template[-margin:]
    template[-2 * margin:-margin] += template[:margin]
    template = template[margin:-margin]
    return template


def find_circular_spots(power_spec, angles, inner=3):
    template = make_circular_template(angles)

    unrolled = unroll_powerspec(power_spec, inner)
    unrolled /= unrolled.max()

    unrolled = np.pad(unrolled, [(unrolled.shape[0] // 2, unrolled.shape[0] // 2), (0, 0)], mode='wrap').astype(
        np.float32)
    h = cv2.matchTemplate(unrolled, template.astype(np.float32), method=2)

    rows, cols = ind2sub(h.shape, h.argmax())

    angles = angles + (rows + .5) / 64 * 2 * np.pi
    radial = cols + inner + 1 + .5
    return radial, angles


def find_hexagonal_spots(power_spec):
    angles = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    return find_circular_spots(power_spec, angles)


def find_hexagonal_scale(image, a):
    power_spec = np.abs(np.fft.fftshift(np.fft.fft2(image))) ** 2
    radial, _ = find_hexagonal_spots(power_spec)
    scale = radial * a / float(min(power_spec.shape)) * (np.sqrt(3.) / 2.)
    return scale


presets = {'graphene':
               {'crystal_system': 'hexagonal',
                'lattice_constant': .246,
                }
           }


class ScaleDetectionModule(StructureRecognitionModule):

    def __init__(self, ui, document_controller):
        super().__init__(ui, document_controller)

        self.crystal_system = None
        self.lattice_constant = None

    def create_widgets(self, column):
        section = Section(self.ui, 'Scale detection')
        column.add(section)

        lattice_constant_row, self.lattice_constant_line_edit = line_edit_template(self.ui, 'Lattice constant [nm]')
        crystal_system_row, self.crystal_system_combo_box = combo_box_template(self.ui, 'Crystal system', ['Hexagonal'])
        section.column.add(crystal_system_row)
        section.column.add(lattice_constant_row)

    def set_preset(self, name):
        self.crystal_system_combo_box.current_item = presets[name]['crystal_system']
        self.lattice_constant_line_edit.text = presets[name]['lattice_constant']

    def fetch_parameters(self):
        self.crystal_system = self.crystal_system_combo_box._widget.current_item.lower()
        self.lattice_constant = float(self.lattice_constant_line_edit._widget.text)

    def detect_scale(self, data):
        assert len(data.shape) == 2

        if self.crystal_system == 'hexagonal':
            scale = find_hexagonal_scale(data, a=self.lattice_constant)

        else:
            raise RuntimeError('structure {} not recognized for scale recognition'.format(self.crystal_system))

        return scale
