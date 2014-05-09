""" fields.py
"""
from enum import IntEnum

from ..errors import PGPError
from .pftypes import PacketField
from .subpackets import SubPacket
from ..util import bytes_to_int, int_to_bytes


class Header(PacketField):
    class Format(IntEnum):
        old = 0
        new = 1

    class Tag(IntEnum):
        ##TODO: implement the rest of these
        Invalid = 0
        Signature = 2
        PrivKey = 5
        PrivSubKey = 7
        PubKey = 6
        Trust = 12
        UserID = 13
        PubSubKey = 14

        @property
        def is_signature(self):
            return self == Header.Tag.Signature

        @property
        def is_key(self):
            return self in [Header.Tag.PubKey, Header.Tag.PubSubKey, Header.Tag.PrivKey, Header.Tag.PrivSubKey]

        @property
        def is_privkey(self):
            return self in [Header.Tag.PrivKey, Header.Tag.PrivSubKey]

        @property
        def is_subkey(self):
            return self in [Header.Tag.PubSubKey, Header.Tag.PrivSubKey]

    def __init__(self, packet=None):
        self.always_1 = 1
        self.format = Header.Format.new
        self.tag = Header.Tag.Invalid
        self.length_type = 0
        ##TODO: length should also be computable from the rest of the packet
        #       this means we'll probably need to store a reference to the Packet object
        #       to which this Header instance belongs
        self.length = 0

        super(Header, self).__init__(packet)

    def parse(self, packet):
        """
        There are two formats for headers

        old style
        ---------

        Old style headers can be 1, 2, 3, or 6 octets long and are composed of a Tag and a Length.
        If the header length is 1 octet (length_type == 3), then there is no Length field.

        new style
        ---------

        New style headers can be 2, 3, or 6 octets long and are also composed of a Tag and a Length.


        Packet Tag
        ----------

        The packet tag is the first byte, comprising the following fields:

        +-------------+----------+---------------+---+---+---+---+----------+----------+
        | byte        | 1                                                              |
        +-------------+----------+---------------+---+---+---+---+----------+----------+
        | bit         | 7        | 6             | 5 | 4 | 3 | 2 | 1        | 0        |
        +-------------+----------+---------------+---+---+---+---+----------+----------+
        | old-style   | always 1 | packet format | packet tag    | length type         |
        | description |          | 0 = old-style |               | 0 = 1 octet         |
        |             |          | 1 = new-style |               | 1 = 2 octets        |
        |             |          |               |               | 2 = 5 octets        |
        |             |          |               |               | 3 = no length field |
        +-------------+          +               +---------------+---------------------+
        | new-style   |          |               | packet tag                          |
        | description |          |               |                                     |
        +-------------+----------+---------------+-------------------------------------+

        :param packet: raw packet bytes
        """
        # parse the tag
        tag = bytes_to_int(packet[:1])

        self.always_1 = tag >> 7
        if self.always_1 != 1:
            raise PGPError("Malformed tag!")  # pragma: no cover

        self.format = Header.Format((tag >> 6) & 1)

        # determine the tag and packet length
        # old style packet header
        if self.format == Header.Format.old:
            self.tag = Header.Tag((tag >> 2) & 0xF)
            self.length_type = tag & 0x3

            if self.length_type == 0:
                packet = packet[:2]

            elif self.length_type == 1:
                packet = packet[:3]

            elif self.length_type == 2:
                packet = packet[:6]

            else:
                packet = packet[:1]

            # if the length is provided, parse it
            if len(packet) > 1:
                self.length = bytes_to_int(packet[1:])

        # new style packet header
        else:
            self.tag = Header.Tag(tag & 0x3F)

            # 1 octet length
            if bytes_to_int(packet[1:2]) < 191:
                self.length = bytes_to_int(packet[1:2])

            # 2 octet length
            if 223 > bytes_to_int(packet[1:2]) > 191:
                # ((num - (192 << 8)) & 0xFF00) + ((num & 0xFF) + 192)
                elen = bytes_to_int(packet[1:3])
                self.length = ((elen - (192 << 8)) & 0xFF00) + ((elen & 0xFF) + 192)

            # 5 octet length
            if bytes_to_int(packet[1:2] == 255):
                self.length = bytes_to_int(packet[2:6])

        # make sure the Tag is valid
        if self.tag == Header.Tag.Invalid:
            raise PGPError("Invalid tag!")  # pragma: no cover

    def __bytes__(self):
        _bytes = b''

        # first byte is bitfields
        fbyte = self.always_1 << 7
        fbyte += self.format << 6

        if self.format == Header.Format.old:
            fbyte += self.tag << 2

            # compute length_type if it isn't already provided
            if self.length_type == 0:
                while self.length >> (8 * (self.length_type + 1)) and self.length_type < 3:
                    self.length_type += 1

            fbyte += self.length_type

        else:
            fbyte += self.tag & 0x3F

        _bytes += int_to_bytes(fbyte)

        if self.format == Header.Format.old:
            _bytes += int_to_bytes(self.length)

        else:
            if self.length < 192:
                _bytes += int_to_bytes(self.length)

            elif self.length < 8384:
                _bytes += int_to_bytes(((self.length & 0xFF00) + (192 << 8)) + abs((self.length & 0xFF) - 192))

            else:
                _bytes += b'x\FF' + int_to_bytes(self.length, 4)

        return _bytes


class SubPackets(PacketField):
    # property method to get the Issuer subpacket
    # realistically, there will only ever be one of these for a given packet
    @property
    def issuer(self):
        nl = [ n.type.name for n in self.subpackets ]
        return self.subpackets[nl.index("Issuer")]

    def __init__(self, packet=None):
        self.length = 0
        self.hashed = False
        self.subpackets = []

        super(SubPackets, self).__init__(packet)

    def parse(self, packet):
        self.length = bytes_to_int(packet[0:2]) + 2
        packet = packet[:self.length]

        pos = 2
        while pos < self.length:
            sp = SubPacket(packet[pos:])
            self.subpackets.append(sp)
            pos += sp.length

    def __bytes__(self):
        _bytes = int_to_bytes(self.length - 2, 2)

        for subpacket in self.subpackets:
            _bytes += subpacket.__bytes__()

        return _bytes
