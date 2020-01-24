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


def top_n_2d(array, n, margin=0):
    top = np.argsort(array.ravel())[::-1]
    accepted = np.zeros((n, 2), dtype=np.int)
    values = np.zeros(n, dtype=np.int)
    marked = np.zeros((array.shape[0] + 2 * margin, array.shape[1] + 2 * margin), dtype=np.bool_)
    i = 0
    j = 0
    while j < n:
        idx = ind2sub(array.shape, top[i])

        if marked[idx[0] + margin, idx[1] + margin] == False:
            marked[idx[0]:idx[0] + 2 * margin, idx[1]:idx[1] + 2 * margin] = True
            marked[margin:2 * margin] += marked[-margin:]
            marked[-2 * margin:-margin] += marked[:margin]

            accepted[j] = idx
            values[j] = array[idx[0], idx[1]]
            j += 1

        i += 1
        if i >= array.size - 1:
            break

    return accepted, values


def moving_average(x, w):
    return np.convolve(x, np.ones(1 + 2 * w), 'valid') / w


def find_circular_spots(power_spec, n, m=1, inner=1, w=2, bins_per_spot=40):
    nbins_angular = n * bins_per_spot

    unrolled = unroll_powerspec(power_spec, inner, nbins_angular=nbins_angular)
    unrolled = unrolled.reshape((n, bins_per_spot, unrolled.shape[1])).sum(0)
    unrolled = unrolled[:, w:-w] / moving_average(unrolled.mean(axis=0), w)
    peaks, intensities = top_n_2d(unrolled, m, bins_per_spot // 4)

    radials, angles = peaks[:, 1], peaks[:, 0]

    angles = (angles + .5) / nbins_angular * 2 * np.pi
    radials = radials + inner + w + .5

    return radials, angles, intensities


def find_hexagonal_scale(image, a=.246, ratio_tol=.1, angle_tol=5., limiting_regime='high'):
    angle_tol = angle_tol / 180. * np.pi

    power_spec = np.fft.fftshift(np.abs(np.fft.fft2(image)) ** 2)
    radials, angles, intensities = find_circular_spots(power_spec, 6, m=2)

    ordered_angles = np.sort(angles)
    ordered_radials = np.sort(radials)
    ratio = ordered_radials[0] / ordered_radials[1]
    angle_diff = np.diff(ordered_angles)[0]

    if np.isclose(ratio, 1 / np.sqrt(3), atol=ratio_tol) & np.isclose(angle_diff, np.pi / 6, atol=angle_tol):
        scale = np.max(radials) * a / float(min(power_spec.shape)) / 2.
    elif limiting_regime == 'low':
        scale = radials[np.argmax(intensities)] * a / float(min(power_spec.shape)) / 2.
    elif limiting_regime == 'high':
        scale = radials[np.argmax(intensities)] * a / float(min(power_spec.shape)) * (np.sqrt(3.) / 2.)
    else:
        raise RuntimeError()

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
