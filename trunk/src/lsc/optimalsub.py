import subutil
from astropy.io import fits
import numpy as np


class ImageClass:
    """Contains the image and relevant parameters"""

    def __init__(self, image_filename, psf_filename):
        self.image_filename = image_filename
        self.psf_filename = psf_filename

        self.raw_image_data = fits.getdata(image_filename)
        self.raw_psf_data = subutil.read_psf_file(psf_filename)

        self.psf_data = subutil.center_psf(subutil.resize_psf(self.raw_psf_data, self.raw_image_data.shape))
        self.zero_point = 1.
        self.background_std, self.background_counts = subutil.fit_noise(self.raw_image_data, n_stamps=4)
        self.saturation_count = subutil.get_saturation_count(image_filename)
        self.pixel_mask = subutil.make_pixel_mask(self.raw_image_data, self.saturation_count)
        self.image_data = subutil.interpolate_bad_pixels(self.raw_image_data, self.pixel_mask) - self.background_counts


def calculate_difference_image(science, reference,
                               normalization='reference', output='output.fits', find_psf=False, n_stamps=1):
    """Calculate the difference image using the Zackey algorithm"""

    # match the gains
    science.zero_point = subutil.solve_iteratively(science, reference)
    reference.zero_point = 1.
    zero_point_ratio = science.zero_point / reference.zero_point

    # create required arrays
    science_image = science.image_data
    reference_image = reference.image_data
    science_psf = science.psf_data
    reference_psf = reference.psf_data

    # do fourier transforms (fft)
    science_image_fft = np.fft.fft2(science_image)
    reference_image_fft = np.fft.fft2(reference_image)
    science_psf_fft = np.fft.fft2(science_psf)
    reference_psf_fft = np.fft.fft2(reference_psf)

    # calculate difference image
    denominator = science.background_std ** 2 * zero_point_ratio ** 2 * abs(science_psf_fft) ** 2
    denominator += reference.background_std ** 2 * abs(reference_psf_fft) ** 2
    difference_image_fft = science_image_fft * reference_psf_fft
    difference_image_fft -= zero_point_ratio * reference_image_fft * science_psf_fft
    difference_image_fft /= np.sqrt(denominator)
    difference_image = np.fft.ifft2(difference_image_fft)

    difference_image = normalize_difference_image(difference_image, science, reference, normalization=normalization)

    save_difference_image_to_file(difference_image, science, normalization, output)

    if find_psf:
        denominator = calculate_difference_image_zero_point(science, reference) * np.sqrt(denominator)
        difference_psf_fft = zero_point_ratio * science_psf_fft * reference_psf_fft / denominator
        difference_psf = np.fft.ifft2(difference_psf_fft)
        save_image_to_file(difference_psf, output.replace('.fits', '.psf.fits'))

    return difference_image


def calculate_matched_filter_image(science, reference, output):
    """Calculate the matched filter image of the difference image and its psf"""

    difference_image = calculate_difference_image(science, reference, output, find_psf=True)
    difference_image_fft = np.fft.fft2(difference_image)
    difference_psf = fits.open(output.replace('.fits', 'psf.fits'))[0].data
    difference_psf_fft = np.fft.fft2(difference_psf)
    difference_zero_point = calculate_difference_image_zero_point(science, reference)

    matched_filter_image_fft = difference_zero_point * difference_image_fft * abs(difference_psf_fft)
    matched_filter_image = np.fft.ifft2(matched_filter_image_fft)

    save_image_to_file(matched_filter_image, output.replace('.fits', '.match.fits'))

    return matched_filter_image


def calculate_difference_image_zero_point(science, reference):
    """Calculate the flux based zero point of the difference image"""

    zero_point_ratio = science.zero_point / reference.zero_point
    denominator = science.background_std ** 2 + reference.background_std ** 2 * zero_point_ratio ** 2
    difference_image_zero_point = zero_point_ratio / np.sqrt(denominator)

    return difference_image_zero_point


def normalize_difference_image(difference, science, reference, normalization='reference'):
    """Normalize to user's choice of image"""

    difference_image_zero_point = calculate_difference_image_zero_point(science, reference)
    if normalization == 'reference' or normalization == 't':
        difference_image = difference * reference.zero_point / difference_image_zero_point
    elif normalization == 'science' or normalization == 'i':
        difference_image = difference * science.zero_point / difference_image_zero_point
    else:
        difference_image = difference

    return difference_image


def save_difference_image_to_file(difference_image, science, normalization, output):
    """Save difference image to file"""

    hdu = fits.PrimaryHDU(np.real(difference_image))
    hdu.header = fits.getheader(science.image_filename)
    hdu.header['PHOTNORM'] = normalization
    hdu.header['CONVOL00'] = normalization
    hdu.writeto(output, overwrite=True, output_verify='warn')


def save_image_to_file(image, output):
    """Save difference image to file"""

    hdu = fits.PrimaryHDU(np.real(image))
    hdu.writeto(output)
    hdu.writeto(output, overwrite=True)

