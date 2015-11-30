import struct
import logging

import gevent
from gevent import socket
from gevent import queue
from gevent import event
from gevent.select import select as gselect

logger = logging.getLogger("Connection")


class Connection:
    MAGIC = 'VT01'
    FMT = '<I4s'
    FMT_SIZE = struct.calcsize(FMT)

    def __init__(self):
        self.socket = None
        self.connected = False
        self.server_addr = None

        self._reader = None
        self._writer = None
        self._readbuf = ''
        self.send_queue = queue.Queue()
        self.recv_queue = queue.Queue()

        self.event_connected = event.Event()

    def connect(self, server_addr):
        self._new_socket()

        logger.debug("Attempting connection to %s", str(server_addr))
        self._connect(server_addr)

        self.server_addr = server_addr

        self._reader = gevent.spawn(self._reader_loop)
        self._writer = gevent.spawn(self._writer_loop)

        logger.debug("Connected.")
        self.event_connected.set()

    def disconnect(self):
        if not self.event_connected.is_set():
            return

        self.server_addr = None

        if self._reader:
            self._reader.kill(block=False)
            self._reader = None
        if self._writer:
            self._writer.kill(block=False)
            self._writer = None

        self._readbuf = ''
        self.send_queue.queue.clear()
        self.recv_queue.queue.clear()

        self.socket.close()

        logger.debug("Disconnected.")
        self.event_connected.clear()

    def get_message(self, block=True, timeout=None):
        return self.recv_queue.get(block, timeout)

    def put_message(self, message):
        self.send_queue.put(message)

    def _writer_loop(self):
        while True:
            message = self.send_queue.get()
            packet = struct.pack(Connection.FMT, len(message), Connection.MAGIC) + message
            try:
                self._write_data(packet)
            except:
                logger.debug("Connection error (writer).")
                self.disconnect()
                return

    def _reader_loop(self):
        while True:
            rlist, _, _ = gselect([self.socket], [], [])

            if self.socket in rlist:
                data = self._read_data()

                if not data:
                    logger.debug("Connection error (reader).")
                    self.disconnect()
                    return

                self._readbuf += data
                self._read_packets()

    def _read_packets(self):
        header_size = Connection.FMT_SIZE
        buf = self._readbuf

        while len(buf) > header_size:
            message_length, magic = struct.unpack_from(Connection.FMT, buf)

            if magic != Connection.MAGIC:
                raise RuntimeError("invalid magic, got %s" % repr(magic))

            packet_length = header_size + message_length

            if len(buf) < packet_length:
                return

            message = buf[header_size:packet_length]
            buf = buf[packet_length:]

            self.recv_queue.put(message)

        self._readbuf = buf


class TCPConnection(Connection):
    def _new_socket(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def _connect(self, server_addr):
        self.socket.connect(server_addr)

    def _read_data(self):
        return self.socket.recv(2048)

    def _write_data(self, data):
        self.socket.sendall(data)


class UDPConnection(Connection):
    def _new_socket(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _connect(self, server_addr):
        pass

    def _read_data(self):
        pass

    def _write_data(self, data):
        pass
