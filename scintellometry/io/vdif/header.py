"""
Definitions for VLBI VDIF Headers.

Implements a VDIFHeader class used to store header words, and decode/encode
the information therein.

For the VDIF specification, see http://www.vlbi.org/vdif
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import numpy as np
import astropy.units as u

from astropy.time import Time, TimeDelta

from ..vlbi_base import (HeaderParser, four_word_struct, eight_word_struct,
                         VLBIHeaderBase)
from ..mark5b.header import Mark5BHeader


ref_max = int(2. * (Time.now().jyear - 2000.)) + 1
ref_epochs = Time(['{y:04d}-{m:02d}-01'.format(y=2000 + ref // 2,
                                               m=1 if ref % 2 == 0 else 7)
                   for ref in range(ref_max)], format='isot', scale='utc',
                  precision=9)


class VDIFHeader(VLBIHeaderBase):
    """VDIF Header, supporting different Extended Data Versions.

    Will initialize a header instance appropriate for a given EDV.
    See http://www.vlbi.org/vdif/docs/VDIF_specification_Release_1.1.1.pdf

    Parameters
    ----------
    words : tuple of int, or None
        Eight (or four for legacy VDIF) 32-bit unsigned int header words.
        If ``None``, set to a tuple of zeros for later initialisation.
    edv : int, False, or None
        Extended data version.  If `False`, a legacy header is used.
        If `None` (default), it is determined from the header.  (Given it
        explicitly is mostly useful for a slight speed-up.)
    verify : bool
        Whether to do basic verification of integrity.  Default: `True`.

    Returns
    -------
    header : VDIFHeader subclass appropriate for the extended data version.
    """

    _properties = ('framesize', 'payloadsize', 'bps', 'nchan',
                   'samples_per_frame', 'station', 'time')
    """Properties accessible/usable in initialisation for all VDIF headers."""

    edv = None

    def __new__(cls, words, edv=None, verify=True):
        # is_legacy_header, get_header_edv, and vdif_header_classes are
        # defined at the end of the file.
        if edv is None:
            if is_legacy_header(words):
                edv = False
            else:
                edv = get_header_edv(words)

        cls = vdif_header_classes.get(edv, VDIFBaseHeader)
        self = super(VDIFHeader, cls).__new__(cls)
        self.edv = edv
        # We intialise VDIFHeader subclasses, so their __init__ will be called.
        return self

    def copy(self):
        return self.__class__(self.words, self.edv, verify=False)

    def same_stream(self, other):
        """Whether header is consistent with being from the same stream."""
        # EDV and most parts of words 2 and 3 should be invariant.
        return (self.edv == other.edv and
                all(self[key] == other[key]
                    for key in ('ref_epoch', 'vdif_version', 'frame_length',
                                'complex_data', 'bits_per_sample',
                                'station_id')))

    @classmethod
    def fromfile(cls, fh, edv=None, verify=True):
        """Read VDIF Header from file.

        Parameters
        ----------
        fh : filehandle
            To read data from.
        edv : int, False, or None
            Extended data version.  If `False`, a legacy header is used.
            If `None` (default), it is determined from the header.  (Given it
            explicitly is mostly useful for a slight speed-up.)
        verify: bool
            Whether to do basic verification of integrity.  Default: `True`.
        """
        # Assume non-legacy header to ensure those are done fastest.
        # Since a payload will follow, it is OK to read too many bytes even
        # for a legacy header; we just rewind below.
        s = fh.read(32)
        if len(s) != 32:
            raise EOFError
        self = cls(eight_word_struct.unpack(s), edv, verify=False)
        if self.edv is False:
            # Legacy headers are 4 words, so rewind, and remove excess data.
            fh.seek(-16, 1)
            self.words = self.words[:4]
        if verify:
            self.verify()

        return self

    @classmethod
    def fromvalues(cls, edv=False, **kwargs):
        """Initialise a header from parsed values.

        Here, the parsed values must be given as keyword arguments, i.e.,
        for any header = cls(<somedata>), cls.fromvalues(**header) == header.

        However, unlike for the 'fromkeys' class method, data can also be set
        using arguments named after header methods such as 'bps' and 'time'.

        Given defaults for standard header keywords:

        invalid_data : `False`
        legacy_mode : `False`
        vdif_version : 1
        thread_id: 0
        frame_nr: 0

        Values set by other keyword arguments (if present):

        bits_per_sample : from 'bps'
        frame_length : from 'framesize' (or 'payloadsize' and 'legacy_mode')
        lg2_nchan : from 'nchan'
        ref_epoch, seconds, frame_nr : from 'time' (may require bandwidth).

        Given defaults for edv 1 and 3:

        sync_pattern: 0xACABFEED.

        Defaults inferred from other keyword arguments for all edv:

        station_id : from 'station'
        sample_rate, sample_unit : from 'bandwidth' or 'framerate'
        """
        # Some defaults that are not done by setting properties.
        kwargs.setdefault('legacy_mode', True if edv is False else False)
        kwargs['edv'] = edv
        return super(VDIFHeader, cls).fromvalues(edv, **kwargs)

    @classmethod
    def fromkeys(cls, **kwargs):
        """Initialise a header from parsed values.

        Like fromvalues, but without any interpretation of keywords.

        Raises
        ------
        KeyError : if not all keys required are present in ``kwargs``
        """
        # Get all required values.
        edv = False if kwargs['legacy_mode'] else kwargs['edv']
        return super(VDIFHeader, cls).fromkeys(edv, **kwargs)

    @classmethod
    def from_mark5b_header(cls, mark5b_header, bps, nchan, **kwargs):
        """Construct an Mark5B over VDIF header (EDV=0xab).

        See http://www.vlbi.org/vdif/docs/vdif_extension_0xab.pdf

        Note that the Mark 5B header does not encode the bits-per-sample and
        the number of channels used in the payload, so these need to be given
        separately.  A complete frame can be encapsulated with
        VDIFFrame.from_mark5b_frame.

        Parameters
        ----------
        mark5b_header : Mark5BHeader
            Used to set time, etc.
        bps : int
            bits per sample.
        nchan : int
            Number of channels carried in the Mark 5B paylod.

        Further arguments are not strictly necessary to create a valid VDIF
        header, but can be given (e.g., ``invalid_data``, etc.)
        """
        kwargs.update(mark5b_header)
        return cls.fromvalues(edv=0xab, time=mark5b_header.time,
                              bps=bps, nchan=nchan, complex_data=False,
                              **kwargs)

    def __repr__(self):
        return ("<{0} {1}>".format(
            self.__class__.__name__, ",\n            ".join(
                ["{0}: {1}".format(k, (hex(self[k]) if k == 'sync_pattern' else
                                       self[k])) for k in self.keys()])))

    # properties common to all VDIF headers.
    @property
    def framesize(self):
        """Size of a frame, in bytes."""
        return self['frame_length'] * 8

    @framesize.setter
    def framesize(self, size):
        assert size % 8 == 0
        self['frame_length'] = int(size) // 8

    @property
    def payloadsize(self):
        """Size of the payload, in bytes."""
        return self.framesize - self.size

    @payloadsize.setter
    def payloadsize(self, size):
        self.framesize = size + self.size

    @property
    def bps(self):
        """Bits per sample (adding bits for imaginary and real for complex)."""
        bps = self['bits_per_sample'] + 1
        if self['complex_data']:
            bps *= 2
        return bps

    @bps.setter
    def bps(self, bps):
        if self['complex_data']:
            bps /= 2
        assert bps % 1 == 0
        self['bits_per_sample'] = int(bps) - 1

    @property
    def nchan(self):
        """Number of channels in frame."""
        return 2**self['lg2_nchan']

    @nchan.setter
    def nchan(self, nchan):
        lg2_nchan = np.log2(nchan)
        assert lg2_nchan % 1 == 0
        self['lg2_nchan'] = int(lg2_nchan)

    @property
    def samples_per_frame(self):
        """Number of samples encoded in frame."""
        # Values are not split over word boundaries.
        values_per_word = 32 // self.bps
        # samples are not split over payload boundaries.
        return self.payloadsize // 4 * values_per_word // self.nchan

    @samples_per_frame.setter
    def samples_per_frame(self, samples_per_frame):
        values_per_long = (32 // self.bps) * 2
        longs, extra = divmod(samples_per_frame * self.nchan,
                              values_per_long)
        if extra:
            longs += 1

        self['frame_length'] = int(longs) + self.size // 8

    @property
    def station(self):
        """Station ID: two ASCII characters, or 16-bit int."""
        msb = self['station_id'] >> 8
        if 48 <= msb < 128:
            return chr(msb) + chr(self['station_id'] & 0xff)
        else:
            return self['station_id']

    @station.setter
    def station(self, station):
        try:
            station_id = (ord(station[0]) << 8) + ord(station[1])
        except TypeError:
            station_id = station
        assert int(station_id) == station_id
        self['station_id'] = station_id

    def get_time(self, framerate=None, frame_nr=None):
        """
        Convert ref_epoch, seconds, and frame_nr to Time object.

        Uses 'ref_epoch', which stores the number of half-years from 2000,
        and 'seconds'.  By default, it also calculates the offset using
        the current frame number.  For non-zero frame_nr, this requires the
        frame rate, which is calculated from the header.  It can be passed on
        if this is not available (e.g., for a legacy VDIF header).

        Set frame_nr=0 to just get the header time from ref_epoch and seconds.

        Parameters
        ----------
        framerate : Quantity with frequency units, or None
            For calculating the offset corresponding to non-zero ``frame_nr``.
            If not given, will try to calculate it from the sampling rate
            given in the header (but not all EDV contain this).
        frame_nr : int or None
            If `None`, uses ``frame_nr`` for this header.
        """
        if frame_nr is None:
            frame_nr = self['frame_nr']

        if frame_nr == 0:
            offset = 0.
        else:
            if framerate is None:
                try:
                    framerate = self.framerate
                except AttributeError:
                    raise ValueError("Cannot calculate frame rate for this "
                                     "header. Pass it in explicitly.")
            offset = (frame_nr / framerate).to(u.s).value
        return (ref_epochs[self['ref_epoch']] +
                TimeDelta(self['seconds'], offset, format='sec', scale='tai'))

    def set_time(self, time, framerate=None):
        """
        Convert Time object to ref_epoch, seconds, and frame_nr.

        For non-integer seconds, the frame_nr will be calculated. This requires
        the frame rate, which is calculated from the header.  It can be passed
        on if this is not available (e.g., for a legacy VDIF header).

        Parameters
        ----------
        time : Time instance
            The time to use for this header.
        framerate : Quantity with frequency units, or None
            For calculating the ``frame_nr`` from the fractional seconds.
            If not given, will try to calculate it from the sampling rate
            given in the header (but not all EDV contain this).
        """
        assert time > ref_epochs[0]
        ref_index = np.searchsorted((ref_epochs - time).sec, 0) - 1
        self['ref_epoch'] = ref_index
        seconds = time - ref_epochs[ref_index]
        int_sec = int(seconds.sec)
        self['seconds'] = int_sec
        frac_sec = seconds - int_sec * u.s
        if abs(frac_sec) < 2. * u.ns:
            self['frame_nr'] = 0
        else:
            if framerate is None:
                try:
                    framerate = self.framerate
                except AttributeError:
                    raise ValueError("Cannot calculate frame rate for this "
                                     "header. Pass it in explicitly.")
            self['frame_nr'] = round((frac_sec * framerate).to(u.one).value)

    time = property(get_time, set_time)


class VDIFLegacyHeader(VDIFHeader):

    _struct = four_word_struct

    # See Section 6 of
    # http://www.vlbi.org/vdif/docs/VDIF_specification_Release_1.1.1.pdf
    _header_parser = HeaderParser(
        (('invalid_data', (0, 31, 1, False)),
         ('legacy_mode', (0, 30, 1, True)),
         ('seconds', (0, 0, 30)),
         ('_1_30_2', (1, 30, 2, 0x0)),
         ('ref_epoch', (1, 24, 6)),
         ('frame_nr', (1, 0, 24, 0x0)),
         ('vdif_version', (2, 29, 3, 0x1)),
         ('lg2_nchan', (2, 24, 5)),
         ('frame_length', (2, 0, 24)),
         ('complex_data', (3, 31, 1)),
         ('bits_per_sample', (3, 26, 5)),
         ('thread_id', (3, 16, 10, 0x0)),
         ('station_id', (3, 0, 16))))

    def __init__(self, words=None, edv=False, verify=True):
        if words is None:
            self.words = (0, 0, 0, 0)
        else:
            self.words = words
        if self.edv is not None:
            self.edv = edv
        if verify:
            self.verify()

    def verify(self):
        """Basic checks of header integrity."""
        assert self.edv is False
        assert self['legacy_mode']
        assert len(self.words) == 4


class VDIFBaseHeader(VDIFHeader):

    _struct = eight_word_struct

    _header_parser = VDIFLegacyHeader._header_parser + HeaderParser(
        (('legacy_mode', (0, 30, 1, False)),  # Repeat, to change default.
         ('edv', (4, 24, 8))))

    def __init__(self, words=None, edv=None, verify=True):
        if words is None:
            self.words = (0, 0, 0, 0, 0, 0, 0, 0)
        else:
            self.words = words
        if edv is not None:
            self.edv = edv
        if verify:
            self.verify()

    def verify(self):
        """Basic checks of header integrity."""
        assert not self['legacy_mode']
        assert self.edv == self['edv']
        assert len(self.words) == 8
        if 'sync_pattern' in self.keys():
            assert (self['sync_pattern'] ==
                    self._header_parser.defaults['sync_pattern'])


class VDIFSampleRateHeader(VDIFBaseHeader):

    # For EDV 1, 3, 4.
    _header_parser = VDIFBaseHeader._header_parser + HeaderParser(
        (('sampling_unit', (4, 23, 1)),
         ('sample_rate', (4, 0, 23)),
         ('sync_pattern', (5, 0, 32, 0xACABFEED))))

    _properties = VDIFBaseHeader._properties + ('bandwidth', 'framerate')

    def same_stream(self, other):
        return (super(VDIFSampleRateHeader, self).same_stream(other) and
                self.words[4] == other.words[4] and
                self.words[5] == other.words[5])

    @property
    def bandwidth(self):
        return u.Quantity(self['sample_rate'],
                          u.MHz if self['sampling_unit'] else u.kHz)

    @bandwidth.setter
    def bandwidth(self, bandwidth):
        self['sampling_unit'] = not (bandwidth.unit == u.kHz or
                                     bandwidth.to(u.MHz).value % 1 != 0)
        if self['sampling_unit']:
            self['sample_rate'] = bandwidth.to(u.MHz).value
        else:
            assert bandwidth.to(u.kHz).value % 1 == 0
            self['sample_rate'] = bandwidth.to(u.kHz).value

    @property
    def framerate(self):
        # Could use self.bandwidth here, but speed up the calculation by
        # changing to a Quantity only at the end.
        return u.Quantity(self['sample_rate'] *
                          (1000000 if self['sampling_unit'] else 1000) *
                          2 * self.nchan / self.samples_per_frame, u.Hz)

    @framerate.setter
    def framerate(self, framerate):
        framerate = framerate.to(u.Hz)
        assert framerate.value % 1 == 0
        self.bandwidth = framerate * self.samples_per_frame / (2 * self.nchan)


class VDIFHeader1(VDIFSampleRateHeader):

    # http://www.vlbi.org/vdif/docs/vdif_extension_0x01.pdf
    _header_parser = VDIFSampleRateHeader._header_parser + HeaderParser(
        (('das_id', (6, 0, 64, 0x0)),))


class VDIFHeader3(VDIFSampleRateHeader):

    # http://www.vlbi.org/vdif/docs/vdif_extension_0x03.pdf
    _header_parser = VDIFSampleRateHeader._header_parser + HeaderParser(
        (('frame_length', (2, 0, 24, 629)),  # Repeat, to set default.
         ('loif_tuning', (6, 0, 32, 0x0)),
         ('_7_28_4', (7, 28, 4, 0x0)),
         ('dbe_unit', (7, 24, 4, 0x0)),
         ('if_nr', (7, 20, 4, 0x0)),
         ('subband', (7, 17, 3, 0x0)),
         ('sideband', (7, 16, 1, False)),
         ('major_rev', (7, 12, 4, 0x0)),
         ('minor_rev', (7, 8, 4, 0x0)),
         ('personality', (7, 0, 8))))

    def verify(self):
        super(VDIFHeader3, self).verify()
        assert self['frame_length'] == 629


class VDIFHeader4(VDIFSampleRateHeader):
    # Used for MWA according to Franz.  No extra header info?
    pass


class VDIFHeader2(VDIFBaseHeader):

    # http://www.vlbi.org/vdif/docs/alma-vdif-edv.pdf
    # Note that this may need to have subclasses, based on possible different
    # sync values.
    _header_parser = VDIFBaseHeader._header_parser + HeaderParser(
        (('complex_data', (3, 31, 1, 0x0)),  # Repeat, to set default.
         ('bits_per_sample', (3, 26, 5, 0x1)),  # Repeat, to set default.
         ('pol', (4, 0, 1)),
         ('BL_quadrant', (4, 1, 2)),
         ('BL_correlator', (4, 3, 1)),
         ('sync_pattern', (4, 4, 20, 0xa5ea5)),
         ('PIC_status', (5, 0, 32)),
         ('PSN', (6, 0, 64))))

    def verify(self):
        super(VDIFHeader2, self).verify()
        assert self['frame_length'] == 629 or self['frame_length'] == 1004
        assert self.bps == 2 and not self['complex_data']


class VDIFMark5BHeader(VDIFBaseHeader, Mark5BHeader):
    """Mark 5B over VDIF (EDV=0xab).

    See http://www.vlbi.org/vdif/docs/vdif_extension_0xab.pdf
    """
    # Repeat 'frame_length' to set default.
    _header_parser = (VDIFBaseHeader._header_parser +
                      HeaderParser((('frame_length', (2, 0, 24, 1254)),)) +
                      HeaderParser(tuple((k, (v[0]+4,) + v[1:]) for (k, v) in
                                         Mark5BHeader._header_parser.items())))

    def verify(self):
        super(VDIFMark5BHeader, self).verify()
        assert self['frame_length'] == 1254  # payload+header=10000+32 bytes/8
        assert abs(self.time - Mark5BHeader.get_time(self)) < 1. * u.ns

    def set_time(self, time):
        super(VDIFMark5BHeader, self).set_time(time)
        Mark5BHeader.set_time(self, time)

    time = property(VDIFHeader.get_time, set_time)


vdif_header_classes = {False: VDIFLegacyHeader,
                       1: VDIFHeader1,
                       2: VDIFHeader2,
                       3: VDIFHeader3,
                       4: VDIFHeader4,
                       0xab: VDIFMark5BHeader}

is_legacy_header = VDIFBaseHeader._header_parser.parsers['legacy_mode']
get_header_edv = VDIFBaseHeader._header_parser.parsers['edv']
