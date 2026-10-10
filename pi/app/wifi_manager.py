"""Asynchronous Wi-Fi changes with observable completion and rollback."""
import copy, hashlib, ipaddress, re, secrets, threading, time


def parse_saved_networks(raw, decode=lambda value: value):
    """An inactive final row can lose its empty flags column after stdout.strip()."""
    networks = {}
    for line in raw.splitlines():
        fields = line.split('\t')
        if len(fields) >= 3 and fields[0].isdigit():
            flags = fields[3] if len(fields) > 3 else ''
            networks[decode(fields[1])] = {'id': int(fields[0]), 'current': 'CURRENT' in flags}
    return networks


class WifiManager:
    def __init__(self, wpa, saved, timeout=55):
        self.wpa, self.saved, self.timeout = wpa, saved, timeout
        self.lock = threading.RLock()
        self.job = {'state': 'idle', 'message': '尚未发起连接', 'active': False}

    def status(self):
        with self.lock:
            result = copy.deepcopy(self.job)
        try:
            fields = dict(x.split('=', 1) for x in self.wpa('status').splitlines() if '=' in x)
            result['connection'] = {k: fields.get(k, '') for k in ('ssid', 'wpa_state', 'ip_address')}
        except Exception:
            result['connection'] = {'wpa_state': 'UNAVAILABLE'}
        return result

    def update(self, **fields):
        with self.lock:
            self.job.update(fields, updated_at=time.time())

    def start(self, ssid='', password='', network_id=None):
        if network_id is None:
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
                raise ValueError('SSID 需为 1–32 字节')
            if not isinstance(password, str) or not 8 <= len(password.encode()) <= 63:
                raise ValueError('WPA2 密码需为 8–63 字节')
        elif type(network_id) is not int or network_id < 0:
            raise ValueError('已保存网络编号无效')
        with self.lock:
            if self.job.get('active'):
                raise ValueError('已有 Wi-Fi 连接任务，请等待当前任务完成')
            self.job = {'id': secrets.token_hex(8), 'state': 'queued', 'active': True,
                        'ssid': ssid, 'message': '已接收连接请求，准备切换网络', 'started_at': time.time()}
            response = copy.deepcopy(self.job)
            # Return the HTTP response before changing the network used by a maintenance tunnel.
            timer = threading.Timer(.7, self.connect, (ssid, password, network_id))
            timer.daemon = True
            timer.start()
            return response

    def command(self, *args):
        result = self.wpa(*args)
        if result != 'OK':
            raise ValueError('无线配置命令未成功：' + args[0])

    def connect(self, ssid, password, network_id):
        new = None
        old = None
        created = network_id is None
        selected = False
        try:
            initial = self.wpa('status')
            match = re.search(r'^id=(\d+)$', initial, re.M)
            old = match.group(1) if match else None
            if created:
                new = self.wpa('add_network')
                if not new.isdigit(): raise ValueError('无法创建 Wi-Fi 配置')
                psk = hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()
                self.command('set_network', new, 'ssid', ssid.encode().hex())
                self.command('set_network', new, 'psk', psk)
                self.command('set_network', new, 'key_mgmt', 'WPA-PSK')
                self.command('set_network', new, 'scan_ssid', '1')
            else:
                known = self.saved()
                names = [name for name, info in known.items() if info['id'] == network_id]
                if not names: raise ValueError('已保存的网络不存在，请重新扫描')
                ssid = names[0]
                self.update(ssid=ssid)
                new = str(network_id)
            self.update(state='associating', message='正在认证并连接 ' + ssid)
            self.command('select_network', new)
            selected = True
            deadline = time.monotonic() + self.timeout
            associated = False
            while time.monotonic() < deadline:
                fields = dict(x.split('=', 1) for x in self.wpa('status').splitlines() if '=' in x)
                if fields.get('id') == new and fields.get('wpa_state') == 'COMPLETED':
                    associated = True
                    self.update(state='dhcp', message='无线认证成功，正在获取 IP 地址')
                    try:
                        address = ipaddress.ip_address(fields.get('ip_address', ''))
                        if address.version != 4 or address.is_link_local or address.is_unspecified:
                            raise ValueError()
                    except ValueError:
                        time.sleep(1)
                        continue
                    self.command('enable_network', 'all')
                    self.command('save_config')
                    self.update(state='connected', active=False, ip_address=str(address),
                                message='已连接 ' + ssid + '，IP：' + str(address))
                    return
                time.sleep(1)
            if associated: raise ValueError('已通过无线认证，但获取 IP 超时，请检查路由器 DHCP')
            raise ValueError('连接超时：请核对密码、2.4 GHz 信号和 WPA2 认证方式')
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else '无线配置服务无响应或命令超时'
            self.update(state='restoring', message=reason + '；正在恢复原网络', error=reason)
            try:
                if created and new and new.isdigit(): self.command('remove_network', new)
                if selected: self.command('enable_network', 'all')
                if old:
                    self.command('select_network', old)
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        fields = dict(x.split('=', 1) for x in self.wpa('status').splitlines() if '=' in x)
                        if fields.get('id') == old and fields.get('wpa_state') == 'COMPLETED':
                            self.update(state='failed', active=False, restored=True,
                                        message=reason + '；已恢复原网络')
                            return
                        time.sleep(1)
                self.update(state='failed', active=False, restored=False,
                            message=reason + '；恢复请求已发出，可通过 USB 或树莓派桌面继续设置')
            except Exception:
                self.update(state='failed', active=False, restored=False,
                            message=reason + '；自动恢复失败，请通过树莓派桌面重新连接')
