import numpy as np
from astropy import units as u
from astropy.tests.helper import pytest
from astropy.time import Time
from .. import mark5b

# Check code on 2015-MAY-08.
# m5d /raw/mhvk/scintillometry/gp052d_wb_no0001 Mark5B-512-8-2 10
#---->first 10016*4 bytes -> sample.m5b
# Mark5 stream: 0x256d140
#   stream = File-1/1=gp052a_wb_no0001
#   format = Mark5B-512-8-2 = 2
#   start mjd/sec = 821 19801.000000000
#   frame duration = 156250.00 ns
#   framenum = 0
#   sample rate = 32000000 Hz
#   offset = 0
#   framebytes = 10016 bytes
#   datasize = 10000 bytes
#   sample granularity = 1
#   frame granularity = 1
#   gframens = 156250
#   payload offset = 16
#   read position = 0
#   data window size = 1048576 bytes
# -3 -1  1 -1  3 -3 -3  3
# -3  3 -1  3 -1 -1 -1  1
#  3 -1  3  3  1 -1  3 -1
# Compare with my code:
# fh = Mark5BData(['/raw/mhvk/scintillometry/gp052d_wb_no0001'],
#                  channels=None, fedge=0, fedge_at_top=True)
# 'Start time: ', '2014-06-13 05:30:01.000' -> correct
# fh.header0
# <Mark5BFrameHeader sync_pattern: 0xabaddeed,
#                    year: 11,
#                    user: 3757,
#                    internal_tvg: False,
#                    frame_nr: 0,
#                    bcd_jday: 0x821,
#                    bcd_seconds: 0x19801,
#                    bcd_fraction: 0x0,
#                    crcc: 38749>
# fh.record_read(6).astype(int)
# array([[-3, -1,  1, -1,  3, -3, -3,  3],
#        [-3,  3, -1,  3, -1, -1, -1,  1],
#        [ 3, -1,  3,  3,  1, -1,  3, -1]])


class TestMark5B(object):
    def test_header(self):
        with open('sample.m5b', 'rb') as fh:
            header = mark5b.Mark5BHeader.fromfile(
                fh, ref_mjd=Time('2014-06-01').mjd)
        assert header.size == 16
        assert header.kday == 56000.
        assert header.jday == 821
        mjd, frac = divmod(header.time.mjd, 1)
        assert mjd == 56821
        assert round(frac * 86400) == 19801
        assert header.payloadsize == 10000
        assert header.framesize == 10016
        assert header['frame_nr'] == 0

        header2 = mark5b.Mark5BHeader.frombytes(header.tobytes(), header.kday)
        assert header2 == header
        header3 = mark5b.Mark5BHeader.fromkeys(header.kday, **header)
        assert header3 == header
        # Try initialising with properties instead of keywords.
        # Here, we let year, bcd_jday, bcd_seconds, and bcd_fraction be
        # set by giving the time.
        header4 = mark5b.Mark5BHeader.fromvalues(
            time=header.time,
            user=header['user'], internal_tvg=header['internal_tvg'],
            frame_nr=header['frame_nr'], crcc=header['crcc'])
        assert header4 == header
        # Check ref_mjd
        header5 = mark5b.Mark5BHeader(header.words,
                                      ref_mjd=(header.time.mjd - 499.))
        assert header5.time == header.time
        header6 = mark5b.Mark5BHeader(header.words,
                                      ref_mjd=(header.time.mjd + 499.))
        assert header6.time == header.time

    def test_payload(self):
        with open('sample.m5b', 'rb') as fh:
            fh.seek(16)  # skip header
            payload = mark5b.Mark5BPayload.fromfile(fh, nchan=8, bps=2)
        assert payload._size == 10000
        assert payload.size == 10000
        assert payload.shape == (5000, 8)
        assert payload.dtype == np.float32
        assert np.all(payload.data[:3].astype(int) ==
                      np.array([[-3, -1, +1, -1, +3, -3, -3, +3],
                                [-3, +3, -1, +3, -1, -1, -1, +1],
                                [+3, -1, +3, +3, +1, -1, +3, -1]]))
        payload2 = mark5b.Mark5BPayload.frombytes(payload.tobytes(),
                                                  payload.nchan, payload.bps)
        assert payload2 == payload
        payload3 = mark5b.Mark5BPayload.fromdata(payload.data, bps=payload.bps)
        assert payload3 == payload
        with pytest.raises(ValueError):
            # Too few bytes.
            mark5b.Mark5BPayload.frombytes(payload.tobytes()[:100],
                                           payload.nchan, payload.bps)

    def test_frame(self):
        with mark5b.open('sample.m5b', 'rb') as fh:
            header = mark5b.Mark5BHeader.fromfile(fh, ref_mjd=57000.)
            payload = mark5b.Mark5BPayload.fromfile(fh, nchan=8, bps=2)
            fh.seek(0)
            frame = fh.read_frame(nchan=8, bps=2)

        assert frame.header == header
        assert frame.payload == payload
        assert frame == mark5b.Mark5BFrame(header, payload)
        assert np.all(frame.data[:3].astype(int) ==
                      np.array([[-3, -1, +1, -1, +3, -3, -3, +3],
                                [-3, +3, -1, +3, -1, -1, -1, +1],
                                [+3, -1, +3, +3, +1, -1, +3, -1]]))
        frame2 = mark5b.Mark5BFrame.frombytes(frame.tobytes(), ref_mjd=57000.,
                                              nchan=frame.shape[1],
                                              bps=frame.payload.bps)
        assert frame2 == frame
        frame3 = mark5b.Mark5BFrame.fromdata(frame.data, frame.header, bps=2)
        assert frame3 == frame

    def test_filestreamer(self):
        with open('sample.m5b', 'rb') as fh:
            header = mark5b.Mark5BHeader.fromfile(fh)

        with mark5b.open('sample.m5b', 'rs', nchan=8, bps=2,
                         sample_rate=16*u.MHz) as fh:
            assert header == fh.header0
            record = fh.read(12)
            assert fh.offset == 12

        assert record.shape == (12, 8)
        assert np.all(record.astype(int)[:3] ==
                      np.array([[-3, -1, +1, -1, +3, -3, -3, +3],
                                [-3, +3, -1, +3, -1, -1, -1, +1],
                                [+3, -1, +3, +3, +1, -1, +3, -1]]))
