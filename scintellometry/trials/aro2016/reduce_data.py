""" work in progress: need to do lofar-style waterfall and foldspec """
from __future__ import division, print_function

import numpy as np
import astropy.units as u

from scintellometry.meta.reduction import reduce, CL_parser

MAX_RMS = 2.
_fref = 600. * u.MHz  # ref. freq. for dispersion measure


def rfi_filter_raw(raw, nchan):
    # note this should accomodate all data (including's lofar raw = complex)
    rawbins = raw.reshape(-1, 2**11*nchan)  # note, this is view!
    std = rawbins.std(-1, keepdims=True)
    ok = std < MAX_RMS
    rawbins *= ok
    return raw, ok


def rfi_filter_power(power, tsr, *args, **kwargs):
    # Detect and store giant pulses in each block through simple S/N test
    buff = 20 # Time range in bins to store of each giant pulse
    power_rfizap = power[:, 1:] # Get rid of RFI channels, currently hardcoded
    if power.shape[-1] == 4:
        freq_av = power_rfizap.sum(1)[:, (0,3)].sum(-1)
    else:
        freq_av = power_rfizap.sum(1).sum(-1)

    #Add a binning factor, not yet implemented
    #freq_av_binned = freq_av.reshape(-1,4).sum(-1)

    sn = (freq_av-freq_av.mean()) / freq_av.std()
    peaks = np.argwhere(sn > 6)
    with open('giant_pulses.txt', 'a') as f:
        f.writelines(['{0} {1}\n'.format(tsr[peak], sn[peak]) for peak in peaks])
    for peak in peaks:
        np.save('GP%s' % (tsr[peak]), power[max(peak-buff,0):min(peak+buff,power.shape[0]),:,:] )
    return power


if __name__ == '__main__':
    args = CL_parser()
    args.verbose = 0 if args.verbose is None else sum(args.verbose)
    if args.fref is None:
        args.fref = _fref

    if args.rfi_filter_raw:
        args.rfi_filter_raw = rfi_filter_raw
    else:
        args.rfi_filter_raw = None

    if args.rfi_filter_power:
        args.rfi_filter_power = rfi_filter_power
    else:
        args.rfi_filter_power = None

    if args.reduction_defaults == 'gmrt':
        args.telescope = 'gmrt'
        args.nchan = 512
        args.ngate = 512
        args.ntbin = 5
        # 170 /(100.*u.MHz/6.) * 512 = 0.0052224 s = 256 bins/pulse
        args.ntw_min = 170
        args.rfi_filter_raw = None
        args.verbose += 1
    reduce(
        args.telescope, args.date, tstart=args.tstart, tend=args.tend,
        nchan=args.nchan, ngate=args.ngate, ntbin=args.ntbin,
        ntw_min=args.ntw_min, rfi_filter_raw=args.rfi_filter_raw,
        rfi_filter_power=args.rfi_filter_power,
        do_waterfall=args.waterfall, do_foldspec=args.foldspec,
        dedisperse=args.dedisperse, fref=args.fref, verbose=args.verbose)
