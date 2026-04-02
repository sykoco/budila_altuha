#!/usr/bin/env python3
"""
Telegram Caller — P2P звонки с использованием tgcalls

Требует:
- pyrogram
- tgcalls (от MarshalX)
"""

import asyncio
import hashlib
import os
import random
import secrets
import struct
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Any

# Pyrogram
try:
    from pyrogram import Client, raw
    from pyrogram.raw import functions, types
    from pyrogram.raw.types import (
        UpdatePhoneCall,
        UpdatePhoneCallSignalingData,
        PhoneCallWaiting,
        PhoneCallAccepted,
        PhoneCall,
        PhoneCallDiscarded,
        PhoneCallDiscardReasonMissed,
        PhoneCallDiscardReasonBusy,
        PhoneCallDiscardReasonHangup,
    )
    from pyrogram.errors import (
        SessionPasswordNeeded,
        FloodWait,
        UserPrivacyRestricted,
        BadRequest,
    )
    from pyrogram.handlers import RawUpdateHandler
    PYROGRAM_AVAILABLE = True
except ImportError as e:
    print(f"Pyrogram error: {e}")
    PYROGRAM_AVAILABLE = False

# tgcalls для VoIP
TGCALLS_AVAILABLE = False
tgcalls = None
try:
    import tgcalls
    TGCALLS_AVAILABLE = True
    print(f"tgcalls loaded: {tgcalls.__version__ if hasattr(tgcalls, '__version__') else 'unknown version'}")
except ImportError as e:
    print(f"tgcalls not available: {e}")

# Настройки
SESSION_FILE = "pyrogram_session"
DEFAULT_RING_DURATION = 30.0
CONFIG_FILE = "caller_config.txt"

# DH параметры
DH_PRIME = int(
    "C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F"
    "48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543AED44CCE7C37"
    "20FD51F69458705AC68CD4FE6B6B13ABDC9746512969328454F18FAF8C595F64"
    "2477FE96BB2A941D5BCD1D4AC8CC49880708FA9B378E3C4F3A9060BEE67CF9A4"
    "A4A695811051907E162753B56B0F6B410DBA74D8A84B2A14B3144E0EF1284754"
    "FD17ED950D5965B4B9DD46582DB1178D169C6BC465B0D6FF9CA3928FEF5B9AE4"
    "E418FC15E83EBEA0F87FA9FF5EED70050DED2849F47BF959D956850CE929851F"
    "0D8115F635B105EE2E4E15D04B2454BF6F4FADF034B10403119CD8E3B92FCC5B",
    16
)
DH_GENERATOR = 3


class CallStatus(Enum):
    SUCCESS = "success"
    ANSWERED = "answered"
    PRIVACY = "privacy"
    NOT_FOUND = "not_found"
    FLOOD = "flood"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"


@dataclass
class CallResult:
    username: str
    status: CallStatus
    message: str
    was_answered: bool = False
    duration: float = 0.0


class TelegramCaller:
    """P2P звонки через Telegram"""
    
    def __init__(self, api_id: int, api_hash: str, session_name: str = SESSION_FILE):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client: Optional[Client] = None
        self.me = None

        # tgcalls instance
        self.call_instance = None

        # Tracking
        self._calls: dict[int, dict] = {}
        self._call_events: dict[int, asyncio.Event] = {}
    
    async def connect(self) -> bool:
        if not PYROGRAM_AVAILABLE:
            return False
        
        try:
            self.client = Client(
                name=self.session_name,
                api_id=self.api_id,
                api_hash=self.api_hash,
                workdir="."
            )
            await self.client.start()
            self.me = await self.client.get_me()
            
            # Raw handler for call updates
            self.client.add_handler(RawUpdateHandler(self._handle_update))
            
            # Initialize tgcalls if available
            if TGCALLS_AVAILABLE:
                self._init_tgcalls()
            
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            if "not authorized" in str(e).lower():
                return await self._authorize()
            return False
    
    def _init_tgcalls(self):
        """Initialize tgcalls for VoIP"""
        try:
            # Try to find available classes/functions in tgcalls
            print(f"tgcalls module contents: {dir(tgcalls)}")
            
            # Check for NTgCalls or similar
            if hasattr(tgcalls, 'NTgCalls'):
                self.call_instance = tgcalls.NTgCalls()
                print("tgcalls.NTgCalls initialized")
            elif hasattr(tgcalls, 'TgCalls'):
                self.call_instance = tgcalls.TgCalls()
                print("tgcalls.TgCalls initialized")
            elif hasattr(tgcalls, 'PrivateCall'):
                print("tgcalls.PrivateCall available")
            else:
                print("tgcalls: looking for private call support...")
        except Exception as e:
            print(f"tgcalls init error: {e}")
    
    async def _authorize(self) -> bool:
        if not sys.stdin.isatty():
            return False
        
        print("\n[Authorization]")
        try:
            self.client = Client(
                name=self.session_name,
                api_id=self.api_id,
                api_hash=self.api_hash,
                workdir="."
            )
            await self.client.connect()
            
            phone = input("Phone (with +): ").strip()
            sent_code = await self.client.send_code(phone)
            code = input("Code: ").strip()
            
            try:
                await self.client.sign_in(phone, sent_code.phone_code_hash, code)
            except SessionPasswordNeeded:
                password = input("2FA: ").strip()
                await self.client.check_password(password)
            
            self.me = await self.client.get_me()
            self.client.add_handler(RawUpdateHandler(self._handle_update))
            return True
        except Exception as e:
            print(f"Auth error: {e}")
            return False
    
    async def _handle_update(self, client, update, users, chats):
        """Handle raw updates"""
        if isinstance(update, UpdatePhoneCall):
            await self._handle_phone_call(client, update.phone_call)
        elif isinstance(update, UpdatePhoneCallSignalingData):
            await self._handle_signaling(client, update)
    
    async def _handle_signaling(self, client, update):
        """Handle WebRTC signaling data"""
        call_id = update.phone_call_id
        data = bytes(update.data)
        
        if call_id not in self._calls:
            return
        
        call_info = self._calls[call_id]
        print(f"   [SIG] Received {len(data)} bytes")
        
        # Process with tgcalls if available
        if self.call_instance and hasattr(self.call_instance, 'receiveSignalingData'):
            try:
                self.call_instance.receiveSignalingData(data)
            except Exception as e:
                print(f"   [SIG ERROR] {e}")
    
    async def _handle_phone_call(self, client, phone_call):
        """Handle phone call state changes"""
        call_id = phone_call.id
        
        if call_id not in self._calls:
            return
        
        call_info = self._calls[call_id]
        
        if isinstance(phone_call, PhoneCallAccepted):
            print(f"\n   [ACCEPTED]")
            
            try:
                g_b = int.from_bytes(phone_call.g_b, byteorder='big')
                private_key = call_info['private_key']
                auth_key = pow(g_b, private_key, DH_PRIME).to_bytes(256, byteorder='big')
                key_fingerprint = struct.unpack('<q', hashlib.sha256(auth_key).digest()[:8])[0]
                g_a_bytes = call_info['g_a'].to_bytes(256, byteorder='big')
                
                result = await client.invoke(
                    functions.phone.ConfirmCall(
                        peer=types.InputPhoneCall(
                            id=call_id,
                            access_hash=phone_call.access_hash
                        ),
                        g_a=g_a_bytes,
                        key_fingerprint=key_fingerprint,
                        protocol=types.PhoneCallProtocol(
                            min_layer=92,
                            max_layer=92,
                            library_versions=['6.0.0', '7.0.0', '8.0.0'],
                            udp_p2p=True,
                            udp_reflector=True
                        )
                    )
                )
                
                confirmed_call = result.phone_call
                call_info['state'] = 'confirmed'
                call_info['auth_key'] = auth_key
                call_info['access_hash'] = confirmed_call.access_hash
                
                if hasattr(confirmed_call, 'connections') and confirmed_call.connections:
                    call_info['connections'] = confirmed_call.connections
                    print(f"   [CONFIRMED] {len(confirmed_call.connections)} endpoints")
                    
                    # Try to start VoIP with tgcalls
                    await self._start_voip(client, call_id, call_info, confirmed_call)
                else:
                    print(f"   [CONFIRMED] No endpoints")
                    call_info['state'] = 'connected'
                    if call_id in self._call_events:
                        self._call_events[call_id].set()
                
            except Exception as e:
                print(f"   [ERROR] {e}")
                import traceback
                traceback.print_exc()
                call_info['state'] = 'error'
                if call_id in self._call_events:
                    self._call_events[call_id].set()
        
        elif isinstance(phone_call, PhoneCall):
            if call_info.get('state') not in ('connected', 'voip'):
                print(f"   [PHONECALL]")
                if hasattr(phone_call, 'connections') and phone_call.connections:
                    await self._start_voip(client, call_id, call_info, phone_call)
                else:
                    call_info['state'] = 'connected'
                    if call_id in self._call_events:
                        self._call_events[call_id].set()
        
        elif isinstance(phone_call, PhoneCallDiscarded):
            reason = phone_call.reason
            was_connected = call_info.get('state') in ('connected', 'voip', 'confirmed')
            
            if isinstance(reason, PhoneCallDiscardReasonBusy):
                call_info['state'] = 'busy'
            elif not was_connected:
                call_info['state'] = 'ended'
            
            reason_name = type(reason).__name__ if reason else 'unknown'
            print(f"   [ENDED] {reason_name}")
            
            if not was_connected and call_id in self._call_events:
                self._call_events[call_id].set()
    
    async def _start_voip(self, client, call_id: int, call_info: dict, phone_call):
        """Start VoIP connection"""
        print(f"   [VOIP] Starting...")
        
        connections = phone_call.connections
        auth_key = call_info.get('auth_key', b'')
        
        # Print connection info
        for i, conn in enumerate(connections[:3]):
            ip = getattr(conn, 'ip', 'N/A')
            port = getattr(conn, 'port', 'N/A')
            print(f"   [VOIP] Server {i+1}: {ip}:{port}")
        
        # Try tgcalls
        if TGCALLS_AVAILABLE and self.call_instance:
            try:
                # Prepare config for tgcalls
                rtc_servers = []
                for conn in connections:
                    server = {
                        'id': str(conn.id),
                        'ip': getattr(conn, 'ip', ''),
                        'ipv6': getattr(conn, 'ipv6', ''),
                        'port': conn.port,
                    }
                    if hasattr(conn, 'peer_tag'):
                        server['peerTag'] = bytes(conn.peer_tag).hex()
                    rtc_servers.append(server)
                
                # Check what methods are available
                available_methods = [m for m in dir(self.call_instance) if not m.startswith('_')]
                print(f"   [VOIP] Available methods: {available_methods[:10]}...")
                
                # Try to connect
                if hasattr(self.call_instance, 'createCall'):
                    self.call_instance.createCall(
                        chatId=call_id,
                        isOutgoing=True,
                        isVideo=False
                    )
                    print(f"   [VOIP] createCall called")
                
                if hasattr(self.call_instance, 'setConnectionMode'):
                    self.call_instance.setConnectionMode(True, True)
                
                call_info['state'] = 'voip'
                
            except Exception as e:
                print(f"   [VOIP ERROR] {e}")
                import traceback
                traceback.print_exc()
        
        call_info['state'] = 'connected'
        if call_id in self._call_events:
            self._call_events[call_id].set()
    
    async def call(
        self,
        username: str,
        duration: float = DEFAULT_RING_DURATION,
        message: Optional[str] = None
    ) -> CallResult:
        """Make a call"""
        if not self.client:
            return CallResult(username, CallStatus.FAILED, "Not connected")
        
        target = username.strip().lstrip("@")
        call_id = None
        
        try:
            # Get user
            try:
                user = await self.client.get_users(int(target) if target.isdigit() else target)
            except Exception:
                return CallResult(username, CallStatus.NOT_FOUND, "User not found")
            
            user_display = f"@{user.username}" if user.username else f"ID:{user.id}"
            
            if message:
                try:
                    await self.client.send_message(user.id, message)
                except Exception:
                    pass
            
            print(f"   Calling {user_display}...", end="", flush=True)
            
            # DH params
            private_key = secrets.randbits(256)
            g_a = pow(DH_GENERATOR, private_key, DH_PRIME)
            g_a_bytes = g_a.to_bytes(256, byteorder='big')
            g_a_hash = hashlib.sha256(g_a_bytes).digest()
            
            input_user = await self.client.resolve_peer(user.id)
            
            # Request call
            result = await self.client.invoke(
                functions.phone.RequestCall(
                    user_id=input_user,
                    g_a_hash=g_a_hash,
                    protocol=types.PhoneCallProtocol(
                        min_layer=92,
                        max_layer=92,
                        library_versions=['6.0.0', '7.0.0', '8.0.0'],
                        udp_p2p=True,
                        udp_reflector=True
                    ),
                    video=False,
                    random_id=secrets.randbelow(2**31)
                )
            )
            
            phone_call = result.phone_call
            call_id = phone_call.id
            access_hash = phone_call.access_hash
            
            self._calls[call_id] = {
                'access_hash': access_hash,
                'private_key': private_key,
                'g_a': g_a,
                'state': 'ringing',
                'user_display': user_display
            }
            self._call_events[call_id] = asyncio.Event()
            
            # Wait for answer
            connected = False
            start = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start) < duration:
                try:
                    await asyncio.wait_for(self._call_events[call_id].wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                
                state = self._calls.get(call_id, {}).get('state', 'ringing')
                if state in ('connected', 'voip', 'confirmed'):
                    connected = True
                    break
                elif state in ('ended', 'busy', 'error'):
                    break
                
                self._call_events[call_id].clear()
            
            if not connected:
                state = self._calls.get(call_id, {}).get('state', 'unknown')
                print(f" [{state.upper()}]")
                
                try:
                    await self.client.invoke(
                        functions.phone.DiscardCall(
                            peer=types.InputPhoneCall(id=call_id, access_hash=access_hash),
                            duration=0,
                            reason=types.PhoneCallDiscardReasonHangup(),
                            connection_id=0
                        )
                    )
                except Exception:
                    pass
                
                if state == 'busy':
                    return CallResult(username, CallStatus.BUSY, "Busy")
                return CallResult(username, CallStatus.NO_ANSWER, "No answer")
            
            # CONNECTED
            print(f" [CONNECTED]")
            call_info = self._calls.get(call_id, {})
            current_access_hash = call_info.get('access_hash', access_hash)

            # Hold line for 30 seconds
            print(f"   Holding line 30 seconds...")
            
            for i in range(30):
                await asyncio.sleep(1)
                if self._calls.get(call_id, {}).get('state') == 'ended':
                    print(f"   [PEER DISCONNECTED at {i}s]")
                    break
            
            # Disconnect
            try:
                await self.client.invoke(
                    functions.phone.DiscardCall(
                        peer=types.InputPhoneCall(id=call_id, access_hash=current_access_hash),
                        duration=30,
                        reason=types.PhoneCallDiscardReasonHangup(),
                        connection_id=0
                    )
                )
            except Exception:
                pass
            
            print(f"   [DONE]")
            return CallResult(username, CallStatus.ANSWERED, "Answered", was_answered=True, duration=30.0)
        
        except UserPrivacyRestricted:
            print(f" [PRIVACY]")
            return CallResult(username, CallStatus.PRIVACY, "Privacy restricted")
        except FloodWait as e:
            print(f" [FLOOD {e.value}s]")
            return CallResult(username, CallStatus.FLOOD, f"Wait {e.value}s")
        except Exception as e:
            print(f" [ERROR] {e}")
            return CallResult(username, CallStatus.FAILED, str(e))
        finally:
            if call_id:
                self._calls.pop(call_id, None)
                self._call_events.pop(call_id, None)
    
    async def call_multiple(self, usernames: list[str], duration: float = DEFAULT_RING_DURATION) -> list[CallResult]:
        results = []
        for i, u in enumerate(usernames, 1):
            print(f"\n[{i}/{len(usernames)}] {u}")
            results.append(await self.call(u, duration))
            if i < len(usernames):
                await asyncio.sleep(2)
        return results
    
    async def disconnect(self):
        if self.client:
            try:
                await self.client.stop()
            except Exception:
                pass


def load_config():
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                lines = f.read().strip().split('\n')
                if len(lines) >= 2:
                    return int(lines[0]), lines[1]
        except Exception:
            pass
    return None, None


def save_config(api_id: int, api_hash: str):
    with open(CONFIG_FILE, 'w') as f:
        f.write(f"{api_id}\n{api_hash}\n")


async def interactive_mode(caller):
    timeout = DEFAULT_RING_DURATION
    
    print(f"\nConnected: @{caller.me.username}")
    print(f"tgcalls: {'Yes' if TGCALLS_AVAILABLE else 'No'}")
    print(f"Audio: {len(caller.sound_files)} files")
    print("\n@username - call | /time N | /quit")
    
    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue
            
            if user_input.startswith("/"):
                cmd = user_input.split()[0].lower()
                arg = user_input[len(cmd):].strip()
                
                if cmd in ("/quit", "/q"):
                    break
                elif cmd == "/time" and arg:
                    try:
                        timeout = float(arg)
                        print(f"Timeout: {timeout}s")
                    except ValueError:
                        pass
                elif cmd == "/sounds":
                    for s in caller.sound_files:
                        print(f"  {s.name}")
                continue
            
            usernames = [p.strip() for p in user_input.replace(",", " ").split() if p.strip()]
            if usernames:
                if len(usernames) == 1:
                    await caller.call(usernames[0], timeout)
                else:
                    await caller.call_multiple(usernames, timeout)
        
        except KeyboardInterrupt:
            break
        except EOFError:
            break


async def main():
    print("\n=== TELEGRAM CALLER ===\n")
    
    api_id, api_hash = load_config()
    
    if not api_id:
        print("Setup: https://my.telegram.org")
        while True:
            try:
                api_id = int(input("API ID: "))
                break
            except ValueError:
                pass
        api_hash = input("API Hash: ").strip()
        save_config(api_id, api_hash)
    
    caller = TelegramCaller(api_id, api_hash)
    
    try:
        print("Connecting...")
        if not await caller.connect():
            print("Failed")
            return
        await interactive_mode(caller)
    finally:
        await caller.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
