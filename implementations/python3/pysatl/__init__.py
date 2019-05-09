
class PySatl(object):
    DATA_SIZE_LIMIT = 1<<16
    INITIAL_BUFFER_LENGTH = 4
    LENLEN = 4
    def __init__(self,is_master,com_driver,skip_init=False):
        self.com = com_driver
        self.is_master=is_master

        if self.com.ack & (False==skip_init):
            #this models the buffer length of the other side
            #our side buffer length is in self.com_driver.bufferlen
            self.other_bufferlen = self.INITIAL_BUFFER_LENGTH

            if is_master:
                self.com.tx(self.com.bufferlen.to_bytes(self.LENLEN,byteorder='little'))
                data = self.com.rx(self.LENLEN)
                self.other_bufferlen = int.from_bytes(data[0:self.LENLEN], byteorder='little', signed=False)
            else:
                data = self.com.rx(self.LENLEN)
                self.other_bufferlen = int.from_bytes(data[0:self.LENLEN], byteorder='little', signed=False)
                self.com.tx(self.com.bufferlen.to_bytes(self.LENLEN,byteorder='little'))

            assert(self.other_bufferlen >= self.com.granularity)
            assert(self.other_bufferlen >= self.com.sfr_granularity)
            assert(0==(self.other_bufferlen % self.com.granularity))
            assert(0==(self.other_bufferlen % self.com.sfr_granularity))
            if self.other_bufferlen<self.com.bufferlen:
                self.com.bufferlen = self.other_bufferlen
        else:
            self.other_bufferlen = self.com.bufferlen
            if not self.com.ack:
                assert(self.other_bufferlen>self.DATA_SIZE_LIMIT+2*self.LENLEN+4)


    def pad(self,buf):
        """pad the buffer if necessary"""
        return Utils.pad(buf,self.com.granularity)

    def padlen(self,l):
        """compute the length of the padded data of length l"""
        return Utils.padlen(l,self.com.granularity)

    def tx(self,apdu):
        if self.is_master:
            self.__master_tx(apdu)
        else:
            self.__slave_tx(apdu)

    def rx(self):
        if self.is_master:
            return self.__master_rx()
        else:
            return self.__slave_rx()

    def __master_tx(self,capdu):
        assert(self.is_master)
        assert(len(capdu.DATA)<=self.DATA_SIZE_LIMIT)
        assert(capdu.LE<=self.DATA_SIZE_LIMIT)
        buf = bytearray()
        fl=len(capdu.DATA) + 4 + 2*self.LENLEN
        buf+=fl.to_bytes(self.LENLEN,byteorder='little')
        buf+=capdu.LE.to_bytes(self.LENLEN,byteorder='little')
        buf.append(capdu.CLA)
        buf.append(capdu.INS)
        buf.append(capdu.P1)
        buf.append(capdu.P2)
        buf+=capdu.DATA
        self.__frame_tx(buf)

    def __master_rx(self):
        assert(self.is_master)
        data = self.__frame_rx()
        fl = int.from_bytes(data[0:self.LENLEN],byteorder='little',signed=False)
        #print(fl)
        sw = fl - 2
        le = max(sw - self.LENLEN,0)
        #print(len(data),le)
        rapdu = RAPDU(data[sw],data[sw+1],data[self.LENLEN:self.LENLEN+le])
        return rapdu

    def __slave_rx(self):
        assert(not self.is_master)
        headerlen = 4+2*self.LENLEN
        data = self.__frame_rx()
        le = int.from_bytes(data[self.LENLEN:2*self.LENLEN],byteorder='little',signed=False)
        h=2*self.LENLEN
        capdu = CAPDU(data[h],data[h+1],data[h+2],data[h+3],data[headerlen:],le)
        return capdu

    def __slave_tx(self,rapdu):
        assert(not self.is_master)
        le = len(rapdu.DATA)
        fl = le + self.LENLEN + 2
        data = bytearray(fl.to_bytes(self.LENLEN,byteorder='little'))
        data+=rapdu.DATA
        data.append(rapdu.SW1)
        data.append(rapdu.SW2)
        self.__frame_tx(data)

    def __frame_tx(self,data):
        """send a complete frame (either a C-TPDU or a R-TPDU), taking care of padding and splitting in chunk"""
        data=self.pad(data)
        #print("padded frame to send: ",data)

        if len(data) < self.other_bufferlen:
            self.com.tx(data)
        else:
            chunks = (len(data)-1) // self.other_bufferlen
            for i in range(0,chunks):
                self.com.tx(data[i*self.other_bufferlen:(i+1)*self.other_bufferlen])
                self.com.rx_ack()
            self.com.tx(data[chunks*self.other_bufferlen:])

    def __frame_rx(self):
        """receive a complete frame (either a C-TPDU or a R-TPDU), return it without pad"""
        flbytes = self.com.rx(self.LENLEN)
        fl = int.from_bytes(flbytes[0:self.LENLEN],byteorder='little',signed=False)

        remaining = fl - len(flbytes)
        #print(fl,remaining)
        data = flbytes
        first_rxlen = min(remaining,self.com.bufferlen- len(flbytes))
        #print("first_rxlen=",first_rxlen)
        dat = self.com.rx(first_rxlen)
        remaining -= len(dat)
        data += dat
        while(remaining>0):
            self.com.tx_ack()
            dat = self.com.rx(min(remaining,self.com.bufferlen))
            remaining -= len(dat)
            data += dat
        #remove padding
        data = data[0:fl]
        #print("received frame: ",data)
        return data

class CAPDU(object):
    """ISO7816-4 C-APDU"""
    def __init__(self,CLA,INS,P1,P2,DATA=bytearray(),LE=0):
        self.CLA = CLA
        self.INS = INS
        self.P1 = P1
        self.P2 = P2
        self.DATA = DATA
        if DATA is None:
            self.DATA = bytearray()
        self.LE = LE

    def __str__(self):
        out = "C-APDU %02X %02X %02X %02X"%(self.CLA,self.INS,self.P1,self.P2)
        if len(self.DATA) > 0:
            out += " - LC=%5d DATA: "%(len(self.DATA))
            out += Utils.hexstr(self.DATA)
        if self.LE>0:
            out += " - LE=%5d"%(self.LE)
        return out

class RAPDU(object):
    """ISO7816-4 R-APDU"""
    def __init__(self,SW1,SW2,DATA=bytearray()):
        self.DATA = DATA
        if DATA is None:
            self.DATA = bytearray()
        self.SW1 = SW1
        self.SW2 = SW2

    def __str__(self):
        out = "R-APDU %02X %02X"%(self.SW1,self.SW2)
        if len(self.DATA) > 0:
            out += " - LE=%5d DATA: "%(len(self.DATA))
            out += Utils.hexstr(self.DATA)
        return out

class SocketComDriver(object):
    """Parameterized model for a communication peripheral and low level rx/tx functions"""
    def __init__(self,sock,bufferlen=4,granularity=1,sfr_granularity=1,ack=True):
        self.sock = sock
        if granularity > sfr_granularity:
            assert(0==(granularity % sfr_granularity))
        if granularity < sfr_granularity:
            assert(0==(sfr_granularity % granularity))
        #shall be power of 2
        assert(1==bin(granularity).count("1"))
        assert(1==bin(sfr_granularity).count("1"))

        self.granularity=granularity
        self.sfr_granularity=sfr_granularity
        self.ack=ack
        if ack:
            self.bufferlen=bufferlen
        else:
            #if no ack then we have hardware flow control, this is equivalent to infinite buffer size
            self.bufferlen = 1<<32 - 1

    def tx_ack(self):
        if self.ack:
            #print("send ack")
            self.sock.send(b'3') #0x33

    def rx_ack(self):
        if self.ack:
            #print("wait ack")
            self.sock.recv(1)
            #print("ack recieved")

    def tx(self,data):
        assert(0==(len(data) % self.sfr_granularity))
        assert(0==(len(data) % self.granularity))
        #print("send ",data)
        self.sock.send(data)

    def rx(self,length):
        assert(length<=self.bufferlen)
        data = bytearray()
        remaining = length+Utils.padlen(length,self.granularity)
        #print("length=",length)
        #print("remaining=",remaining)
        while(remaining):
            #print("remaining=",remaining)
            #print("receive: ",end="")
            dat = self.sock.recv(remaining)
            if 0==len(dat):
                raise Exception("Connection broken")
            #print(dat)
            data += dat
            remaining -= len(dat)
        if self.ack & (len(data)>self.bufferlen):
            raise ValueError("RX overflow, data length = %d"%len(data))
        assert(0==(len(data) % self.granularity))

        #padding due to SFRs granularity
        data = Utils.pad(data,self.sfr_granularity)
        #print("received data length after padding = ",len(data))
        return data


class StreamComDriver(object):
    """Parameterized model for a communication peripheral and low level rx/tx functions"""
    def __init__(self,stream,bufferlen=3,granularity=1,sfr_granularity=1):
        self.stream = stream
        if granularity > sfr_granularity:
            assert(0==(granularity % sfr_granularity))
        if granularity < sfr_granularity:
            assert(0==(sfr_granularity % granularity))
        #shall be power of 2
        assert(1==bin(granularity).count("1"))
        assert(1==bin(sfr_granularity).count("1"))

        self.bufferlen=bufferlen
        self.granularity=granularity
        self.sfr_granularity=sfr_granularity

    def tx(self,data):
        assert(0==(len(data) % self.sfr_granularity))
        assert(0==(len(data) % self.granularity))
        self.stream.write(data)

    def rx(self,length):
        data = bytearray()
        while(len(data)<length):
            dat = self.stream.read(self.granularity)
            data += dat
        if len(data)>self.bufferlen:
            raise("RX overflow, data length = ",len(data))
        assert(0==(len(data) % self.granularity))

        #padding due to SFRs granularity
        data = Utils.pad(data,self.sfr_granularity)
        return data

class Utils(object):
    @staticmethod
    def pad(buf,granularity):
        """pad the buffer if necessary (with zeroes)"""
        l = len(buf)
        if 0 != (l % granularity):
            v=0
            buf += v.to_bytes(Utils.padlen(l,granularity),'little')
        return buf

    @staticmethod
    def padlen(l,granularity):
        """compute the length of the pad for data of length l to get the requested granularity"""
        nunits = (l+granularity-1) // granularity
        return granularity * nunits - l

    @staticmethod
    def hexstr(bytes, head="", separator=" ", tail=""):
        """Returns an hex string representing bytes
        @param bytes:  a list of bytes to stringify,
                    e.g. [59, 22, 148, 32, 2, 1, 0, 0, 13]
                    or a bytearray
        @param head: the string you want in front of each bytes. Empty by default.
        @param separator: the string you want between each bytes. One space by default.
        @param tail: the string you want after each bytes. Empty by default.
        """
        if bytes is not bytearray:
            bytes = bytearray(bytes)
        if (bytes is None) or bytes == []:
            return ""
        else:
            pformat = head+"%-0.2X"+tail
            return (separator.join(map(lambda a: pformat % ((a + 256) % 256), bytes))).rstrip()

    @staticmethod
    def int_to_bytes(x, width=-1, byteorder='little'):
        if width<0:
            width = (x.bit_length() + 7) // 8
        b = x.to_bytes(width, byteorder)
        return b

    @staticmethod
    def int_to_ba(x, width=-1, byteorder='little'):
        if width<0:
            width = (x.bit_length() + 7) // 8
        b = x.to_bytes(width, byteorder)
        return bytearray(b)

    @staticmethod
    def to_int(ba, byteorder='little'):
        b = bytes(ba)
        return int.from_bytes(b, byteorder)

    @staticmethod
    def ba(hexstr_or_int):
        """Extract hex numbers from a string and returns them as a bytearray
        It also handles int and list of int as argument
        If it cannot convert, it raises ValueError
        """
        try:
            t1 = hexstr_or_int.lower()
            t2 = "".join([c if c.isalnum() else " " for c in t1])
            t3 = t2.split(" ")
            out = bytearray()
            for bstr in t3:
                if bstr != "":
                    l = len(bstr)
                    if(l % 2):
                        bstr = "0"+bstr
                        l+=1
                    for p in range(0,l,2):
                        s=bstr[p:p+2]
                        out.extend((bytearray.fromhex(s)))
        except:
            #seems arg is not a string, assume it is a int
            try:
                out = int_to_ba(hexstr_or_int)
            except:
                # seems arg is not an int, assume it is a list
                try:
                    out = bytearray(hexstr_or_int)
                except:
                    raise ValueError()
        return out