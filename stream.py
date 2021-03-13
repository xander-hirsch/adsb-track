import os
import sqlite3
import pyModeS as pms
from pyModeS.extra.tcpclient import TcpClient

import adsb_track.database as database
from adsb_track.aircraft import Aircraft


TC_POS = tuple(range(9, 19)) + tuple(range(20, 23))


class Database:
    def __init__(self, name, buffer=50):
        self.con = sqlite3.connect(name)
        self.cur = self.con.cursor()
        self.max_buffer = buffer
        self.buffer = 0
        # self.gs_lat = gs_lat
        # self.gs_lon = gs_lon
        database.initialize(self.con, self.cur)


    def commit(self):
        # print('buffer cleared')
        self.con.commit()
        self.buffer = 0


    def log(func):
        def wrapper(self, *args, **kwargs):
            self.buffer += 1

            func(self, *args, **kwargs)

            if self.buffer >= self.max_buffer:
                self.commit()

        return wrapper


    @log
    def log_ident(self, ts, icao, callsign, tc, category):
        database.insert_ident(self.cur, ts, icao, callsign, tc, category)

    @log
    def log_velocity(self, ts, icao, spd, angle, vs, spd_type, angle_src, vs_src):
        database.insert_velocity(self.cur, ts, icao, spd, angle, vs, spd_type, angle_src, vs_src)

    @log
    def log_position(self, ts, icao, lat, lon, alt, alt_src):
        database.insert_position(self.cur, ts, icao, lat, lon, alt, alt_src)


class FlightRecorder(TcpClient):
    def __init__(self, host, db, gs_lat, gs_lon, port=30005, rawtype='beast', buffer=25):
        super(FlightRecorder, self).__init__(host, port, rawtype)
        self.gs_lat = gs_lat
        self.gs_lon = gs_lon
        self.airspace = {}
        self.db = Database(db, buffer)

    def process_msg(self, msg, ts, icao, tc):
        if tc in TC_POS:
            self.process_position(msg, ts, icao, tc)
        elif tc == 19:
            self.process_velocity(msg, ts, icao)
        elif tc in tuple(range(1,5)):
            self.process_ident(msg, ts, icao, tc)

    def process_position(self, msg, ts, icao, tc):
        alt_src = 'BARO' if tc < 19 else 'GNSS'
        alt = pms.adsb.altitude(msg)
        lat, lon = pms.adsb.position_with_ref(msg, self.gs_lat, self.gs_lon)

        self.db.log_position(ts, icao, lat, lon, alt, alt_src)

        if icao not in self.airspace:
            self.airspace[icao] = Aircraft(icao)
        self.airspace[icao].update_position(ts, lat, lon, alt)

    def process_velocity(self, msg, ts, icao):
        velocity = pms.adsb.velocity(msg, True)
        heading = velocity[1]
        speed = velocity[0]
        vertical_speed = velocity[2]

        self.db.log_velocity(ts, icao, *velocity)

        if icao not in self.airspace:
            self.airspace[icao] = Aircraft(icao)
        self.airspace[icao].update_velocity(ts, heading, speed, vertical_speed)

    def process_ident(self, msg, ts, icao, tc):
        callsign = pms.adsb.callsign(msg).strip('_')
        category = pms.adsb.category(msg)

        self.db.log_ident(ts, icao, callsign, tc, category)

        if icao not in self.airspace:
            self.airspace[icao] = Aircraft(icao)
        self.airspace[icao].update_callsign(ts, callsign)

    def handle_messages(self, messages):
        for msg, ts in messages:
            if not all((len(msg)==28, pms.df(msg)==17, pms.crc(msg)==0)):
                continue

            icao = pms.adsb.icao(msg)
            tc = pms.adsb.typecode(msg)

            self.process_msg(msg, ts, icao, tc)

    def record(self):
        try:
            self.run()
        except KeyboardInterrupt:
            self.db.commit()


if __name__ == '__main__':
    gs_lat = float(os.environ.get('ADSB_LATITUDE', '34'))
    gs_lon = float(os.environ.get('ADSB_LONGITUDE', '-118.2'))
    # client = ADSBClient('pi.lan.xanderhirsch.us')
    # client.run()
    client = FlightRecorder('pi.lan.xanderhirsch.us', 'test.db', gs_lat, gs_lon)
    client.record()
