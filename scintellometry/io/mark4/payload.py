"""
Definitions for VLBI Mark 4 payloads.

Implements a Mark4Payload class used to store payload words, and decode to
or encode from a data array.

For the specification, see
http://www.haystack.mit.edu/tech/vlbi/mark5/docs/230.3.pdf
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import sys
import numpy as np
from ..vlbi_base import (VLBIPayloadBase, encode_2bit_real_base,
                         OPTIMAL_2BIT_HIGH)


#  2bit/fanout4 use the following in decoding 32 and 64 track data:
if sys.byteorder == 'big':
    def reorder32(x):
        return (((x & 0x55AA55AA)) |
                ((x & 0xAA00AA00) >> 9) |
                ((x & 0x00550055) << 9))

    def reorder64(x):
        return (((x & 0x55AA55AA55AA55AA)) |
                ((x & 0xAA00AA00AA00AA00) >> 9) |
                ((x & 0x0055005500550055) << 9))
else:
    def reorder32(x):
        return (((x & 0xAA55AA55)) |
                ((x & 0x55005500) >> 7) |
                ((x & 0x00AA00AA) << 7))

    # can speed this up from 140 to 132 us by predefining bit patterns as
    # array scalars.  Inplace calculations do not seem to help much.
    def reorder64(x):
        return (((x & 0xAA55AA55AA55AA55)) |
                ((x & 0x5500550055005500) >> 7) |
                ((x & 0x00AA00AA00AA00AA) << 7))
    # check on 2015-JUL-12: C code: 738811025863578102 -> 738829572664316278
    # 118, 209, 53, 244, 148, 217, 64, 10
    # reorder64(np.array([738811025863578102], dtype=np.uint64))
    # # array([738829572664316278], dtype=uint64)
    # reorder64(np.array([738811025863578102], dtype=np.uint64)).view(np.uint8)
    # # array([118, 209,  53, 244, 148, 217,  64,  10], dtype=uint8)
    # decode_2bit_64track_fanout4(
    #     np.array([738811025863578102], dtype=np.int64)).astype(int).T
    # -1  1  3  1  array([[-1,  1,  3,  1],
    #  1  1  3 -3         [ 1,  1,  3, -3],
    #  1 -3  1  3         [ 1, -3,  1,  3],
    # -3  1  3  3         [-3,  1,  3,  3],
    # -3  1  1 -1         [-3,  1,  1, -1],
    # -3 -3 -3  1         [-3, -3, -3,  1],
    #  1 -1  1  3         [ 1, -1,  1,  3],
    # -1 -1 -3 -3         [-1, -1, -3, -3]])


def init_luts():
    """Set up the look-up tables for levels as a function of input byte."""
    lut2level = np.array([1.0, -1.0], dtype=np.float32)
    lut4level = np.array([-OPTIMAL_2BIT_HIGH, 1.0, -1.0, OPTIMAL_2BIT_HIGH],
                         dtype=np.float32)
    b = np.arange(256)[:, np.newaxis]
    # lut1bit
    i = np.arange(8)
    # For all 1-bit modes
    lut1bit = lut2level[(b >> i) & 1]
    i = np.arange(4)
    # fanout 1 @ 8/16t, fanout 4 @ 32/64t
    s = i*2
    m = s+1
    lut2bit1 = lut4level[(b >> s & 1) +
                         (b >> m & 1) * 2]
    # fanout 2 @ 8/16t, fanout 1 @ 32/64t
    s = i + (i//2)*2  # 0, 1, 4, 5
    m = s + 2         # 2, 3, 6, 7
    lut2bit2 = lut4level[(b >> s & 1) +
                         (b >> m & 1) * 2]
    # fanout 4 @ 8/16t, fanout 2 @ 32/64t
    s = i    # 0, 1, 2, 3
    m = s+4  # 4, 5, 6, 7
    lut2bit3 = lut4level[(b >> s & 1) +
                         (b >> m & 1) * 2]
    return lut1bit, lut2bit1, lut2bit2, lut2bit3

lut1bit, lut2bit1, lut2bit2, lut2bit3 = init_luts()

# Look-up table for the number of bits in a byte.
nbits = ((np.arange(256)[:, np.newaxis] >> np.arange(8) & 1)
         .sum(1).astype(np.int16))


def decode_8chan_2bit_fanout4(frame, out=None):
    """Decode frame for 8 channels using 2 bits, fan-out 4 (64 tracks)."""
    # Bitwise reordering of tracks, to align sign and magnitude bits,
    # reshaping to get VLBI channels in sequential, but wrong order.
    frame = reorder64(frame).view(np.uint8).reshape(-1, 8)
    # Correct ordering, at the same time possibly selecting specific channels.
    frame = frame.take(np.array([0, 2, 1, 3, 4, 6, 5, 7]), axis=1)
    # The look-up table splits each data byte into 4 measurements.
    # Using transpose ensures channels are first, then time samples, then
    # those 4 measurements, so the reshape orders the samples correctly.
    # Another transpose ensures samples are the first dimension.
    if out is None:
        return lut2bit1.take(frame.T, axis=0).reshape(8, -1).T
    else:
        # in-place decoding is about a factor 2 slower, so probably not
        # useful, but provided for consistency.
        outf4 = out.reshape(-1, 4, 8).transpose(2, 0, 1)
        assert outf4.base is out or outf4.base is out.base
        lut2bit1.take(frame.T, axis=0, out=outf4)
        return out


def encode_8chan_2bit_fanout4(values):
    """Decode frame using 8 channels, 2 bits, fan-out 4."""
    reorder_channels = np.array([0, 2, 1, 3, 4, 6, 5, 7])
    values = values[:, reorder_channels].reshape(-1, 4, 8).transpose(0, 2, 1)
    bitvalues = encode_2bit_real_base(values)
    reorder_bits = np.array([0, 2, 1, 3], dtype=np.uint8)
    reorder_bits.take(bitvalues, out=bitvalues)
    bitvalues <<= np.array([0, 2, 4, 6], dtype=np.uint8)
    out = np.bitwise_or.reduce(bitvalues, axis=-1).ravel().view(np.uint64)
    return reorder64(out)


class Mark4Payload(VLBIPayloadBase):
    """Container for decoding and encoding VDIF payloads.

    Parameters
    ----------
    words : ndarray
        Array containg LSB unsigned words (with the right size) that
        encode the payload.
    nchan : int
        Number of channels in the data.  Default: 1.
    bps : int
        Number of bits per complete sample.  Default: 2.
    fanout : int
        Number of tracks every bit stream is spread over.

    The number of tracks is nchan * bps * fanout.
    """

    # Decoders keyed by (nchan, nbit, fanout).
    _encoders = {(8, 2, 4): encode_8chan_2bit_fanout4}
    _decoders = {(8, 2, 4): decode_8chan_2bit_fanout4}

    def __init__(self, words, header=None, nchan=1, bps=2, fanout=1):
        if header is not None:
            nchan = header.nchan
            bps = header.bps
            fanout = header.fanout
            self._size = header.payloadsize
        self.fanout = fanout
        super(Mark4Payload, self).__init__(words, nchan, bps,
                                           complex_data=False)

    @classmethod
    def fromfile(cls, fh, header):
        """Read payload from file handle and decode it into data.

        The payloadsize, number of channels, bits per sample, and fanout ratio
        are all taken from the header.
        """
        s = fh.read(header.payloadsize)
        if len(s) < header.payloadsize:
            raise EOFError("Could not read full payload.")
        return cls(np.fromstring(s, dtype=header.stream_dtype), header)

    @classmethod
    def fromdata(cls, data, header):
        """Encode data as payload, using header information."""
        if data.dtype.kind == 'c':
            raise ValueError("Mark4 format does not support complex data.")
        if header.nchan != data.shape[-1]:
            raise ValueError("Header is for {0} channels but data has {1}"
                             .format(header.nchan, data.shape[-1]))
        encoder = cls._encoders[header.nchan, header.bps, header.fanout]
        words = encoder(data)
        return cls(words, header)

    def todata(self, data=None):
        """Decode the payload.

        Parameters
        ----------
        data : ndarray or None
            If given, used to decode the payload into.  It should have the
            right size to store it.  Its shape is not changed.
        """
        decoder = self._decoders[self.nchan, self.bps, self.fanout]
        return decoder(self.words, out=data)

    data = property(todata, doc="Decode the payload.")
