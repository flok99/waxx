#!/usr/bin/env python3
#
# Glicko-1 computation by Gian-Carlo Pascutto

import time
import math


def rd_update(rd, last_update):
    # Find RD update constants, assuming the time for
    # RD=50 to get to RD=350 is 2 years (bit faster than
    # the paper, as we are considering bots).
    # 350 = sqrt(50^2 + c^2 * 365 * 2)
    # 350^2 = 50^2 + c^2 * 730
    # 350^2 - 50^2 = c^2 * 730
    # 350^2 - 50^2 / 730 = c^2
    # c = sqrt((350^2 - 50^2) / 730)
    # c = 12.8
    c = (((350.0**2.0) - (50.0**2.0)) / (365.0 * 2.0))**0.5

    # compute days since last update
    t = (time.time() - last_update) / (60.0 * 60.0 * 24.0)

    # compute RD increase
    new_rd = min((rd**2.0 + ((c**2.0) * t))**0.5, 350.0)

    return new_rd


def calc_g(rd):
    q = math.log(10) / 400.0
    denom = 1.0 + ((3.0 * (q**2.0) * (rd**2.0)) / (math.pi**2.0))
    return 1.0 / (denom**0.5)


def calc_e(rdj, r, rj):
    denom = 1.0 + 10**(-calc_g(rdj) * (r - rj) / 400.0)
    return 1.0 / denom


def calc_glicko(rating_1, rd_1, last_update_1, rating_2, rd_2, last_update_2,
                result):
    assert (result == 0 or result == 1 or result == 0.5)
    pre_rd_1 = rd_update(rd_1, last_update_1)
    pre_rd_2 = rd_update(rd_2, last_update_2)

    e = calc_e(pre_rd_2, rating_1, rating_2)
    g = calc_g(pre_rd_2)

    q = math.log(10) / 400.0
    d2 = 1.0 / ((q**2) * (g**2) * e * (1.0 - e))

    rating_inc = q / ((1.0 / (pre_rd_1**2)) + (1.0 / d2)) * g * (result - e)
    rating_new = rating_1 + rating_inc

    # Reduce RD
    rd_new = (1.0 / ((1.0 / (pre_rd_1**2)) + (1.0 / d2)))**0.5

    # Clamp minimum RD at 30
    rd_new = max(rd_new, 30)

    return (rating_new, rd_new)


def main():
    # unknown player
    rating_1 = 1500
    rd_1 = 350
    last_update_1 = 0
    # known player
    rating_2 = 1800
    rd_2 = 80
    last_update_2 = time.time() - (2 * 24 * 60 * 60)

    new_rating_1, new_rd_1 = calc_glicko(rating_1, rd_1, last_update_1,
                                         rating_2, rd_2, last_update_2, 1.0)
    # Note this needs the player 1 values from before the update
    new_rating_2, new_rd_2 = calc_glicko(rating_2, rd_2, last_update_2,
                                         rating_1, rd_1, last_update_1, 0.0)

    rating_1 = new_rating_1
    rd_1 = new_rd_1
    rating_2 = new_rating_2
    rd_2 = new_rd_2
    last_update_1 = time.time()
    last_update_2 = time.time()

    # Rating and confidence interval
    print("r1={:.0f}±{:.1f}".format(rating_1, 1.96 * rd_1))
    print("r2={:.0f}±{:.1f}".format(rating_2, 1.96 * rd_2))

    # ...time passes...RD's increase
    rd_1 = rd_update(rd_1, last_update_1)
    rd_2 = rd_update(rd_2, last_update_2)
    last_update_1 = time.time()
    last_update_2 = time.time()

    # Ratings stay the same but RD (uncertainty) rises
    print("r1={:.0f}±{:.1f}".format(rating_1, 1.96 * rd_1))
    print("r2={:.0f}±{:.1f}".format(rating_2, 1.96 * rd_2))


if __name__ == "__main__":
    main()

def glicko_wrapper(rating_1, rd_1, last_update_1, rating_2, rd_2, last_update_2, result):
    if result == '1-0':
        new_rating_1, new_rd_1 = calc_glicko(rating_1, rd_1, last_update_1, rating_2, rd_2, last_update_2, 1.0)
        new_rating_2, new_rd_2 = calc_glicko(rating_2, rd_2, last_update_2, rating_1, rd_1, last_update_1, 0.0)
    elif result == '0-1':
        new_rating_1, new_rd_1 = calc_glicko(rating_1, rd_1, last_update_1, rating_2, rd_2, last_update_2, 0.0)
        new_rating_2, new_rd_2 = calc_glicko(rating_2, rd_2, last_update_2, rating_1, rd_1, last_update_1, 1.0)
    else:
        new_rating_1, new_rd_1 = calc_glicko(rating_1, rd_1, last_update_1, rating_2, rd_2, last_update_2, 0.5)
        new_rating_2, new_rd_2 = calc_glicko(rating_2, rd_2, last_update_2, rating_1, rd_1, last_update_1, 0.5)

    return new_rating_1, new_rd_1, new_rating_2, new_rd_2
