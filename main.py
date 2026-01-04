"""ngeng"""

import curses
from math import e
from time import monotonic
from typing import TypeVar
from lymia import ReturnType, Scene, const, on_key, run
from lymia.colors import ColorPair, Coloring, color
from lymia.data import SceneResult
from lymia.environment import Theme
from lymia.progress import Progress

number = TypeVar("number", int, float)


def now():
    """Return now"""
    return monotonic()


def timed(seconds: float):
    """time"""
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return hours, minutes, secs


def clamp(num: number, minvalue: number, maxvalue: number):
    """Clamp"""
    return max(minvalue, min(num, maxvalue))


MAX_SPEED            = {0: 0.00, 1: 3.00, 2: 6.00, 3: 18.0, 4: 32.0}
ACCEL_BONUS          = {0: 0.00, 1: 0.02, 2: 0.05, 3: 0.25, 4: 0.50}
ACCEL_MULT_THRESHOLD = {0: 0.00, 1: 0.00, 2: 0.25, 3: 0.25, 4: 0.90}
ACCEL_DROP_THRESHOLD = {0: 0.00, 1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00}
#MAX_SPEED            = {0: 0.0, 1: 3.0, 2: 6.0, 3: 18.0, 4: 32.0, 5: 64.0, 6: 128.0, 7: 256.0, 8: 512.0, 9: 1024, 10: 2048, 11: 99_999, 12: 9_999_999, 13: 99_999_999}
#ACCEL_BONUS          = {0: 0, 1: 2.25, 2: 5, 3: 8, 4: 10, 5: 15, 6: 18, 7: 22, 8: 24, 9: 48, 10: 96, 11: 999, 12: 9_999, 13: 9_999_999}
#ACCEL_MULT_THRESHOLD = {0: 0.0, 1: 0.0, 2: 0.25, 3: 0.25, 4: 0.50, 5: 0.60, 6: 0.65, 7: 0.75, 8: 0.75, 9: 0.75, 10: 0.90, 11: 0.0, 12: 0.0, 13: 0.0}
#ACCEL_DROP_THRESHOLD = {0: 0.0, 1: 0.0, 2: 1.00, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.00, 7: 1.00, 8: 1.00, 9: 1.00, 10: 1.00, 11: 1.0, 12: 1.2, 13: 2.0}
GEAR_KEYS = tuple(MAX_SPEED.keys())
GEAR_NAME = ("Neutral", "Gear #1", "Gear #2", "Gear #3", "Gear #4")
#GEAR_NAME = ("Neutral", "Gear #1", "Gear #2", "Gear #3", "Gear #4", "Gear #5", "Gear #6", "Gear #7", "Gear #8", "Gear #9", "Gear #10", "Gear MAX", "Gear ULTRA", "Gear ProMAX")

ACCEL = 6.0
DRAG = 2.5
ENGINE_BRAKE = 2.0
BRAKE_FORCE = 8.0
UNIT_SCALING = 1
DOWNSHIFT_BRAKE = 10.0
CRUISE_RESPONSE = 5.0
ACCEL_BONUS_MULT_THRESHOLD = 0.5
DROP_THRESHOLD = 0.0

INCREMENTAL_CURVE_SHARPNESS = 30
DECREMENTAL_CURVE_SHARPNESS = 30

MAX_DISTANCE = 36_000 * UNIT_SCALING / 1000
#_acl_mult = lambda speed, maxspd, dropmult: max((speed / maxspd), 0.1)

def _acl_thmult(mult: float, acm: float):
    return 1 / (1 + e**(-INCREMENTAL_CURVE_SHARPNESS * (mult - acm)))

def _drp_thmult(mult: float, dcm: float):
    return 1 / (1 + e**(DECREMENTAL_CURVE_SHARPNESS * (2 * (mult - dcm))))

def _acl_mult(speed: number, maxspd: number, accel_mult: float, drop_mult: float):
    if maxspd == 0 or speed > maxspd:
        return 0
    mult = speed / maxspd
    accel_threshold = _acl_thmult(mult, accel_mult)
    drop_threshold = _drp_thmult(mult, drop_mult)
    return min(mult * accel_threshold * drop_threshold, 1)

def acl_mult(speed: number,
             maxspd: number,
             raw: bool = False,
             mult_threshold: float = ACCEL_BONUS_MULT_THRESHOLD,
             drop_threshold: float = DROP_THRESHOLD) -> number:
    return _acl_mult(speed, maxspd, mult_threshold, drop_threshold)

def acceleration_bonus(speed: number, gear: int) -> number:
    maxspd = MAX_SPEED[gear]
    acl_bonus = ACCEL_BONUS[gear]
    threshold = ACCEL_MULT_THRESHOLD.get(gear, ACCEL_BONUS_MULT_THRESHOLD)
    drop = ACCEL_DROP_THRESHOLD.get(gear, DROP_THRESHOLD)
    base_mult = acl_mult(speed, maxspd, mult_threshold=threshold, drop_threshold=drop)
    if speed > maxspd:
        return 0
    return acl_bonus * base_mult

class Basic(Coloring):
    """Basic coloring"""

    DOWNSHIFT = ColorPair(color.RED, -1)
    SPEED_UP = ColorPair(color.GREEN, -1)
    SPEED_DOWN = ColorPair(color.RED, -1)


class Root(Scene):
    """Root scene"""

    use_default_color = True
    render_fps = 60

    def __init__(self) -> None:
        super().__init__()
        self._hold_key: int = -1
        self._hold_timeout = 0.15
        self._last_forward_event = -1
        self._forward_active = True
        self.gear = 1
        self.last_gear = 0
        self._last_time = 0
        self.speed = 0
        self.distance = 0
        self.brake_active = False
        self.last_brake_event = -1
        self.cruise_active = False
        self.cruise_speed = 0.0
        self.elapsed_time = 0
        self.progress = Progress()
        self.downshift = False

    def init(self, stdscr: curses.window):
        super().init(stdscr)
        curses.set_escdelay(2)

    def draw(self) -> None | ReturnType:
        width, height = self.term_size
        n = now()
        lspeed = self.speed
        ren = self._screen
        if self._last_time == 0:
            delta_time = 0
        else:
            delta_time = n - self._last_time
        self._last_time = n
        self.elapsed_time += delta_time

        if self.brake_active:
            self.speed -= BRAKE_FORCE * delta_time
        # elif not self._forward_active:
        #     self.speed -= ENGINE_BRAKE * delta_time

        if self.brake_active and (n - self.last_brake_event) > self._hold_timeout:
            self._hold_key = -1
            self.brake_active = False

        if self.cruise_active:
            target = self.cruise_speed
            self.speed += (target - self.speed) * CRUISE_RESPONSE * delta_time

        if (n - self._last_forward_event) > self._hold_timeout:
            self._hold_key = -1
            self._forward_active = False
        if self.gear != 0:
            if self._forward_active:
                accel_bonus = acceleration_bonus(self.speed, self.gear)
                self.speed += (ACCEL + accel_bonus) * delta_time
            else:
                self.speed -= DRAG * delta_time
        else:
            self.speed -= DRAG * delta_time

        if self.speed > MAX_SPEED[self.gear]:
            self.speed -= DOWNSHIFT_BRAKE * delta_time
            self.speed -= (
                MAX_SPEED[self.last_gear] * DOWNSHIFT_BRAKE * delta_time
                if self.cruise_active
                else 0
            )
            self.cruise_active = False
            self.downshift = True
        else:
            self.downshift = False

        self.speed = max(self.speed, 0)
        self.distance += self.speed * delta_time

        if round(self.speed, 2) > round(lspeed, 2):
            pointer = "↑"
            pstyle = Basic.SPEED_UP.pair()
        elif round(self.speed, 2) < round(lspeed, 2):
            pointer = "↓"
            pstyle = Basic.SPEED_DOWN.pair()
        else:
            pointer = "↻"
            pstyle = 0

        downshifting = self.speed > MAX_SPEED[self.gear] and self.last_gear > self.gear
        ds_style = Basic.DOWNSHIFT.pair() if downshifting else 0

        distance = self.distance * UNIT_SCALING / 1000
        speed = self.speed * UNIT_SCALING * 3.6

        h, m, s = timed(self.elapsed_time)
        elapsed_time = f"{h:02d}:{m:02d}:{s:02d}"
        cruise = "[CRUISE]" if self.cruise_active else "[      ]"
        brake = "[BRAKE]" if self.brake_active else "[     ]"
        maxspd = f"{MAX_SPEED[self.gear] * UNIT_SCALING * 3.6:,.2f}km/h"
        control_gear = f"[Gear: {GEAR_NAME[self.gear]}]"
        acl_thr = ACCEL_MULT_THRESHOLD[self.gear]
        drop_thr = ACCEL_DROP_THRESHOLD[self.gear]
        acl_mlt = acl_mult(self.speed, MAX_SPEED[self.gear], mult_threshold=acl_thr, drop_threshold=drop_thr)
        max_speed_ctl = f"[Max SPD: {maxspd}] ({acl_mlt*100:.4f}%)"
        progress = (distance / MAX_DISTANCE) * 100
        progress_speed = (
            f"{progress:.2f}% [{distance:,.2f}km] | {speed:,.2f}km/h @ {elapsed_time}"
        )
        try:
            self.progress.render(
                ren,
                0,
                0,
                width - 5,
                min(distance, MAX_DISTANCE),  # type: ignore
                MAX_DISTANCE, # type: ignore
                prefix="",
                only_bar=True,
            )  # type: ignore
            ren.addstr(1, 0, f"{progress_speed:^{width}}")
            plen = len(progress_speed)
            ren.addstr(1, width // 2 + plen // 2 + 2, pointer, pstyle)
            ren.addstr(2, 0, f"{control_gear} | [q/e] {max_speed_ctl}", ds_style)
            ren.addstr(3, 0, f"{cruise}        | [tab]")
            ren.addstr(4, 0, f"{brake}         | [s]")
        except curses.error as e:
            e.add_note(f"Terminal dimension: {height}x{width}")
            raise e
        self.show_status()

    @on_key("w", curses.KEY_UP)
    def forward(self) -> ReturnType:
        """Go forward"""
        self._forward_active = True
        self._last_forward_event = now()
        return ReturnType.OK

    @on_key("s", curses.KEY_DOWN)
    def brake(self) -> ReturnType:
        """Brake"""
        self.brake_active = True
        self.last_brake_event = now()
        return ReturnType.OK

    @on_key("q")
    def gear_shiftup(self):
        """Gear shift"""
        if self.gear == len(MAX_SPEED) - 1:
            self.last_gear = self.gear
            self.gear = 0
            return ReturnType.OK
        self.last_gear = self.gear
        self.gear += 1
        return ReturnType.OK

    @on_key("e")
    def gear_shiftdown(self):
        """Gear shift"""
        if self.gear == 0:
            self.last_gear = self.gear
            self.gear = len(MAX_SPEED) - 1
            return ReturnType.OK
        self.last_gear = self.gear
        self.gear -= 1
        return ReturnType.OK

    @on_key(9)
    def cruise_toggle(self):
        """Cruise"""
        self.cruise_active = not self.cruise_active
        self.cruise_speed = self.speed
        return ReturnType.OK

    @on_key(const.KEY_ESC)
    def quit(self) -> ReturnType:
        """Exit"""
        return ReturnType.EXIT

    def handle_key(self, key: int) -> ReturnType | SceneResult:
        # if key != -1:
        # status.set(f"({chr(key)} | {key})")
        return super().handle_key(key)


def init():
    """init"""
    return Root(), Theme(0, Basic())


if __name__ == "__main__":
    run(init)
