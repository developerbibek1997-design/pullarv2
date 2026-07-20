"""Puller (SDK edition) — attendance puller for meroattendance.com.

This build talks to the ZKTeco terminal through the official ZKTeco
Standalone SDK (the `zkemkeeper` COM component) instead of the pure-Python
`pyzk` library. Newer devices such as the MB1000/ID accept the official SDK
but reject pyzk's handshake (WinError 10054), so this edition connects the
same way the official "Attendance Management Program" does.

Requirements on the target PC:
  * Windows (the SDK is Windows/COM only).
  * The ZKTeco SDK must be registered — installing the official ZKTeco
    software (or running `regsvr32 zkemkeeper.dll`) does this.
  * This program must be 32-bit, because zkemkeeper.dll is 32-bit.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import datetime
import threading
import json
import os
import queue
import platform
import sys

import requests
from PIL import Image, ImageTk

# COM / ZKTeco SDK (Windows only). Imported lazily-safely so the file can at
# least be inspected on non-Windows machines.
try:
    import pythoncom
    import win32com.client
    HAVE_COM = True
except Exception:
    HAVE_COM = False


REQUEST_TIMEOUT = 15
API_BASE = "https://www.meroattendance.com"


def resource_path(relative_path):
    """Absolute path to a bundled read-only resource (images, icon)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_data_dir():
    """Persistent, user-writable directory for app config."""
    system = platform.system()
    if system == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    elif system == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))
    data_dir = os.path.join(base, 'Puller')
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        data_dir = os.path.abspath('.')
    return data_dir


CONFIG_PATH = os.path.join(get_data_dir(), 'device.json')


def load_device_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
            return cfg.get('ip', ''), cfg.get('port', 0), cfg.get('password', 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return '', 0, 0


def save_device_config(ip, port, password=0):
    with open(CONFIG_PATH, 'w') as f:
        json.dump({'ip': ip, 'port': port, 'password': password}, f)


# ---------------------------------------------------------------------------
# ZKTeco SDK device wrapper
# ---------------------------------------------------------------------------
class ZKDevice:
    """Thin wrapper over the zkemkeeper COM object.

    Create, connect, use and disconnect within a *single* thread. Each worker
    thread must call pythoncom.CoInitialize() before using this class (see
    com_thread()).
    """

    MACHINE = 1  # SDK machine number; a single connection uses 1

    def __init__(self, ip, port, password=0):
        self.ip = ip
        self.port = int(port)
        self.password = int(password or 0)
        self.zk = None

    # -- connection -------------------------------------------------------
    def connect(self):
        if not HAVE_COM:
            raise Exception("ZKTeco SDK not available (Windows only).")
        try:
            self.zk = win32com.client.Dispatch("zkemkeeper.ZKEM")
        except Exception as e:
            raise Exception(
                "Could not load the ZKTeco SDK (zkemkeeper). Install the "
                "official ZKTeco software or register zkemkeeper.dll.\n\n"
                f"Details: {e}"
            )
        if self.password:
            try:
                self.zk.SetCommPassword(self.password)
            except Exception:
                pass
        ok = self.zk.Connect_Net(self.ip, self.port)
        if not ok:
            code = self._last_error()
            self.zk = None
            raise Exception(f"Connect_Net({self.ip}:{self.port}) failed (SDK error {code}).")
        return True

    def disconnect(self):
        if self.zk is not None:
            try:
                self.zk.Disconnect()
            except Exception:
                pass
            self.zk = None

    def _last_error(self):
        try:
            res = self.zk.GetLastError()
            if isinstance(res, (tuple, list)):
                return res[-1]
            return res
        except Exception:
            return "?"

    # -- attendance -------------------------------------------------------
    def get_attendance(self):
        """Return a list of (enroll_id:str, 'YYYY-MM-DD HH:MM:SS') tuples."""
        zk = self.zk
        records = []
        zk.EnableDevice(self.MACHINE, False)
        try:
            if zk.ReadGeneralLogData(self.MACHINE):
                while True:
                    data = zk.SSR_GetGeneralLogData(self.MACHINE)
                    if not data or not data[0]:
                        break
                    # (ret, enroll, verify, inout, Y, M, D, h, m, s, workcode)
                    enroll = str(data[1])
                    y, mo, d, h, mi, s = (int(data[4]), int(data[5]), int(data[6]),
                                          int(data[7]), int(data[8]), int(data[9]))
                    ts = f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
                    records.append((enroll, ts))
        finally:
            zk.EnableDevice(self.MACHINE, True)
        return records

    def clear_attendance(self):
        try:
            self.zk.ClearGLog(self.MACHINE)
        except Exception:
            pass

    # -- users ------------------------------------------------------------
    def get_users(self):
        """Return list of dicts: {uid, name, privilege, enabled}."""
        zk = self.zk
        users = []
        zk.EnableDevice(self.MACHINE, False)
        try:
            if zk.ReadAllUserID(self.MACHINE):
                while True:
                    data = zk.SSR_GetAllUserInfo(self.MACHINE)
                    if not data or not data[0]:
                        break
                    # (ret, enroll, name, password, privilege, enabled)
                    users.append({
                        'uid': str(data[1]),
                        'name': data[2],
                        'privilege': int(data[4]) if data[4] is not None else 0,
                        'enabled': bool(data[5]),
                    })
        finally:
            zk.EnableDevice(self.MACHINE, True)
        return users

    def set_user(self, uid, name, card=0, privilege=0):
        zk = self.zk
        zk.EnableDevice(self.MACHINE, False)
        try:
            if card:
                try:
                    zk.SetStrCardNumber(str(card))
                except Exception:
                    pass
            zk.SSR_SetUserInfo(self.MACHINE, str(uid), str(name), "", int(privilege), True)
            try:
                zk.RefreshData(self.MACHINE)
            except Exception:
                pass
        finally:
            zk.EnableDevice(self.MACHINE, True)

    def delete_user(self, uid):
        zk = self.zk
        zk.EnableDevice(self.MACHINE, False)
        try:
            zk.SSR_DeleteEnrollData(self.MACHINE, str(uid), 12)  # 12 = whole user
            try:
                zk.RefreshData(self.MACHINE)
            except Exception:
                pass
        finally:
            zk.EnableDevice(self.MACHINE, True)

    # -- power ------------------------------------------------------------
    def restart(self):
        self.zk.RestartDevice(self.MACHINE)

    def poweroff(self):
        self.zk.PowerOffDevice(self.MACHINE)


def com_thread(target):
    """Wrap a thread target so COM is initialised for that thread."""
    def runner(*args, **kwargs):
        if HAVE_COM:
            pythoncom.CoInitialize()
        try:
            target(*args, **kwargs)
        finally:
            if HAVE_COM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
    return runner


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
member_list = []
classification_list = []
organization = ""
device_list = []
org_id = 0
device_ip, device_port, device_password = load_device_config()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class PullerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Puller (SDK) - meroattendance.com')
        self.geometry('900x560')
        self.resizable(True, True)
        self.minsize(760, 620)

        try:
            icon_path = resource_path('images/image.ico' if platform.system() == 'Windows' else 'images/image.png')
            if platform.system() == 'Windows':
                self.iconbitmap(icon_path)
            else:
                self.iconphoto(False, ImageTk.PhotoImage(Image.open(icon_path)))
        except Exception as e:
            print(f"Could not load icon: {e}")

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('.', background='#f8f9fa', font=('Segoe UI', 10))
        self.style.configure('TFrame', background='#f8f9fa')
        self.style.configure('TLabel', background='#f8f9fa')
        self.style.configure('TButton', padding=8)
        self.style.configure('Primary.TButton', foreground='white', background='#4f46e5')
        self.style.configure('Success.TButton', foreground='white', background='#28a745')
        self.style.configure('Danger.TButton', foreground='white', background='#dc3545')
        self.style.configure('Warning.TButton', foreground='white', background='#ffc107')
        self.style.configure('Info.TButton', foreground='white', background='#17a2b8')
        self.style.configure('Treeview', rowheight=25)
        self.style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))
        self.style.map('Treeview', background=[('selected', '#4f46e5')])

        self.container = ttk.Frame(self)
        self.container.pack(fill='both', expand=True, padx=10, pady=10)

        self.frames = {}
        for F in (Homepage, Dashboard):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky='nsew')
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.show_frame('Homepage')

        self.message_queue = queue.Queue()
        self.after(100, self.process_queue)

        if not HAVE_COM:
            self.after(500, lambda: messagebox.showwarning(
                "SDK unavailable",
                "The ZKTeco SDK is only available on Windows. Device features "
                "will not work on this system."))

    def process_queue(self):
        while not self.message_queue.empty():
            try:
                msg = self.message_queue.get_nowait()
                if msg[0] == 'messagebox':
                    getattr(messagebox, msg[1])(**msg[2])
                elif msg[0] == 'method':
                    getattr(msg[1], msg[2])(*msg[3], **msg[4])
            except queue.Empty:
                break
        self.after(100, self.process_queue)

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        frame.tkraise()
        frame.event_generate('<<ShowFrame>>')


class Homepage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        card = ttk.Frame(main_frame)
        card.place(relx=0.5, rely=0.5, anchor='center')

        ttk.Label(card, text="🔐 Puller Login (SDK)", font=('Segoe UI', 20, 'bold'),
                  foreground='#1e40af').pack(pady=(0, 20))

        ttk.Label(card, text="Organization PIN:", font=('Segoe UI', 11)).pack(anchor='w')
        self.org_pin = ttk.Entry(card, width=32, font=('Segoe UI', 12))
        self.org_pin.pack(fill='x', ipady=6, pady=(4, 12))
        self.org_pin.bind('<Return>', lambda e: self.check_code())

        self.progress = ttk.Progressbar(card, orient='horizontal', mode='determinate', length=320)
        self.progress.pack(fill='x', pady=(0, 12))

        self.check_btn = ttk.Button(card, text="Verify & Continue →",
                                    style='Primary.TButton', command=self.check_code)
        self.check_btn.pack(fill='x', ipady=6)

        self.status_label = ttk.Label(card, text="", foreground='#dc3545', font=('Segoe UI', 9))
        self.status_label.pack(pady=(10, 0))

    def check_code(self):
        code = self.org_pin.get().strip()
        if not code:
            self.set_status("Organization PIN is required", error=True)
            return
        self.check_btn.config(state='disabled')
        self.progress['value'] = 5
        self.set_status("Connecting to server...")
        threading.Thread(target=self._check_thread, args=(code,), daemon=True).start()

    def _check_thread(self, code):
        try:
            orgs = requests.get(f"{API_BASE}/organizationlist", timeout=REQUEST_TIMEOUT).json()
            self.progress['value'] = 15
            org = next((o for o in orgs if o.get('serial_key') == code), None)
            if not org:
                self.set_status("Invalid Puller Code", error=True)
                return
            self._load_org(org)
            self.controller.show_frame('Dashboard')
            self.org_pin.delete(0, 'end')
            self.progress['value'] = 0
            self.set_status("")
        except Exception as e:
            self.set_status(f"Error: {e}", error=True)
        finally:
            self.check_btn.config(state='normal')

    def _load_org(self, org):
        global organization, org_id, member_list, classification_list, device_list
        organization = org['name']
        org_id = org['id']

        self.set_status("Fetching members...")
        self.progress['value'] = 40
        member_list = [m for m in requests.get(f"{API_BASE}/member", timeout=REQUEST_TIMEOUT).json()
                       if m.get('org') == org_id]

        self.set_status("Fetching classifications...")
        self.progress['value'] = 65
        classification_list = [c for c in requests.get(f"{API_BASE}/classification", timeout=REQUEST_TIMEOUT).json()
                               if c.get('org') == org_id]

        self.set_status("Fetching devices...")
        self.progress['value'] = 90
        device_list = [d for d in requests.get(f"{API_BASE}/device", timeout=REQUEST_TIMEOUT).json()
                       if d.get('org') == org_id]
        self.progress['value'] = 100

    def set_status(self, text, error=False):
        self.status_label.config(text=text, foreground='#dc3545' if error else '#16a34a')


class Dashboard(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.scanning = False
        self.live_device = None

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)

        self.dashboard_tab = ttk.Frame(self.notebook)
        self.members_tab = ttk.Frame(self.notebook)
        self.devices_tab = ttk.Frame(self.notebook)
        self.live_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.dashboard_tab, text=' Dashboard ')
        self.notebook.add(self.members_tab, text=' Members ')
        self.notebook.add(self.devices_tab, text=' Devices ')
        self.notebook.add(self.live_tab, text=' Live Attendance ')

        self.init_dashboard_tab()
        self.init_members_tab()
        self.init_devices_tab()
        self.init_live_tab()

        self.bind('<<ShowFrame>>', lambda e: self.update_dashboard_data())

    # -- dashboard tab ----------------------------------------------------
    def init_dashboard_tab(self):
        header = ttk.Frame(self.dashboard_tab)
        header.pack(fill='x', padx=20, pady=20)
        self.org_label = ttk.Label(header, text="Organization: ", font=('Segoe UI', 14, 'bold'))
        self.org_label.pack(side='left')
        ttk.Button(header, text="Refresh Data", style='Info.TButton',
                   command=self.refresh_data).pack(side='right')

        stats = ttk.Frame(self.dashboard_tab)
        stats.pack(fill='x', padx=20, pady=10)
        self.mem_count = self._stat(stats, "Total Members")
        self.class_count = self._stat(stats, "Total Classifications")
        self.dev_count = self._stat(stats, "Total Devices")

        btns = ttk.Frame(self.dashboard_tab)
        btns.pack(fill='x', padx=20, pady=20)

        ctrl = ttk.LabelFrame(btns, text="Device Controls", padding=10)
        ctrl.pack(side='left', fill='both', expand=True, padx=5)
        ttk.Button(ctrl, text="Check Connection", style='Info.TButton',
                   command=self.check_connection).pack(fill='x', pady=5)
        ttk.Button(ctrl, text="Pull Attendance Data", style='Success.TButton',
                   command=self.pull_data).pack(fill='x', pady=5)
        ttk.Button(ctrl, text="Restart Device", style='Warning.TButton',
                   command=self.restart_device).pack(fill='x', pady=5)
        ttk.Button(ctrl, text="Power Off Device", style='Danger.TButton',
                   command=self.power_off).pack(fill='x', pady=5)

        memctrl = ttk.LabelFrame(btns, text="Member Controls", padding=10)
        memctrl.pack(side='left', fill='both', expand=True, padx=5)
        ttk.Button(memctrl, text="Sync Members", style='Primary.TButton',
                   command=self.sync_members).pack(fill='x', pady=5)

        self.status_var = tk.StringVar()
        ttk.Label(self.dashboard_tab, textvariable=self.status_var,
                  foreground='#28a745', font=('Segoe UI', 9)).pack(anchor='w', padx=20)

    def _stat(self, parent, title):
        frame = ttk.Frame(parent)
        frame.pack(side='left', fill='both', expand=True, padx=5, ipady=10)
        ttk.Label(frame, text=title, font=('Segoe UI', 10)).pack(pady=(10, 5))
        lbl = ttk.Label(frame, text="0", font=('Segoe UI', 24, 'bold'))
        lbl.pack(pady=(0, 10))
        return lbl

    # -- members tab ------------------------------------------------------
    def init_members_tab(self):
        search = ttk.Frame(self.members_tab)
        search.pack(fill='x', padx=20, pady=10)
        ttk.Label(search, text="Search:").pack(side='left', padx=(0, 10))
        self.mem_search = ttk.Entry(search)
        self.mem_search.pack(side='left', fill='x', expand=True)
        self.mem_search.bind('<KeyRelease>', lambda e: self.search_members())
        self.mem_count_label = ttk.Label(search, text="", foreground='#6c757d')
        self.mem_count_label.pack(side='left', padx=(10, 0))

        list_frame = ttk.Frame(self.members_tab)
        list_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        cols = ('name', 'card', 'email', 'phone', 'device_id')
        self.member_tree = ttk.Treeview(list_frame, columns=cols, show='headings')
        for c, t, w in (('name', 'Name', 180), ('card', 'Card', 90), ('email', 'Email', 180),
                        ('phone', 'Phone', 110), ('device_id', 'Device ID', 90)):
            self.member_tree.heading(c, text=t)
            self.member_tree.column(c, width=w, anchor='w')
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.member_tree.yview)
        self.member_tree.configure(yscrollcommand=sb.set)
        self.member_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    # -- devices tab ------------------------------------------------------
    def init_devices_tab(self):
        top = ttk.Frame(self.devices_tab)
        top.pack(fill='x', padx=20, pady=(20, 0))
        self.primary_label = ttk.Label(top, text="Primary device: none",
                                        font=('Segoe UI', 10, 'bold'), foreground='#17a2b8')
        self.primary_label.pack(side='left')

        add = ttk.LabelFrame(self.devices_tab, text="Add / Set Device", padding=10)
        add.pack(fill='x', padx=20, pady=(10, 0))
        ttk.Label(add, text="Name:").pack(side='left', padx=(0, 4))
        self.dev_name_entry = ttk.Entry(add, width=12)
        self.dev_name_entry.pack(side='left', padx=(0, 8))
        ttk.Label(add, text="IP:").pack(side='left', padx=(0, 4))
        self.dev_ip_entry = ttk.Entry(add, width=15)
        self.dev_ip_entry.pack(side='left', padx=(0, 8))
        ttk.Label(add, text="Port:").pack(side='left', padx=(0, 4))
        self.dev_port_entry = ttk.Entry(add, width=7)
        self.dev_port_entry.insert(0, '4370')
        self.dev_port_entry.pack(side='left', padx=(0, 8))
        ttk.Label(add, text="Comm Key:").pack(side='left', padx=(0, 4))
        self.dev_pw_entry = ttk.Entry(add, width=7)
        self.dev_pw_entry.insert(0, str(device_password or 0))
        self.dev_pw_entry.pack(side='left', padx=(0, 8))
        ttk.Button(add, text="Add & Set Primary", style='Success.TButton',
                   command=self.add_manual_device).pack(side='left', padx=5)

        list_frame = ttk.Frame(self.devices_tab)
        list_frame.pack(fill='both', expand=True, padx=20, pady=20)
        cols = ('name', 'ip', 'port', 'primary')
        self.device_tree = ttk.Treeview(list_frame, columns=cols, show='headings', selectmode='browse')
        for c, t, w in (('name', 'Name', 160), ('ip', 'IP Address', 150),
                        ('port', 'Port', 80), ('primary', 'Primary', 80)):
            self.device_tree.heading(c, text=t)
            self.device_tree.column(c, width=w, anchor='w')
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=sb.set)
        self.device_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        ctrl = ttk.Frame(self.devices_tab)
        ctrl.pack(fill='x', padx=20, pady=(0, 20))
        ttk.Button(ctrl, text="Set Selected as Primary", style='Primary.TButton',
                   command=self.set_primary_device).pack(side='left', fill='x', expand=True, padx=5)
        ttk.Button(ctrl, text="Refresh Devices", style='Info.TButton',
                   command=self.refresh_data).pack(side='left', fill='x', expand=True, padx=5)

    # -- live tab ---------------------------------------------------------
    def init_live_tab(self):
        frame = ttk.Frame(self.live_tab)
        frame.pack(fill='both', expand=True, padx=20, pady=20)
        self.live_logs = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=('Consolas', 10),
                                                    state='disabled', height=15)
        self.live_logs.pack(fill='both', expand=True)

        ctrl = ttk.Frame(self.live_tab)
        ctrl.pack(fill='x', padx=20, pady=(0, 20))
        self.scan_btn = ttk.Button(ctrl, text="Start Live Scan", style='Success.TButton',
                                   command=self.toggle_live_scan)
        self.scan_btn.pack(side='left', fill='x', expand=True, padx=5)
        ttk.Button(ctrl, text="Clear Logs", style='Danger.TButton',
                   command=self.clear_logs).pack(side='left', fill='x', expand=True, padx=5)
        self.live_status = ttk.Label(self.live_tab, text="Status: Ready", foreground='#6c757d')
        self.live_status.pack(anchor='w', padx=20, pady=(0, 10))

    # -- data refresh -----------------------------------------------------
    def update_dashboard_data(self):
        self.org_label.config(text=f"Organization: {organization}")
        self.mem_count.config(text=str(len(member_list)))
        self.class_count.config(text=str(len(classification_list)))
        self.dev_count.config(text=str(len(device_list)))

        self.member_tree.delete(*self.member_tree.get_children())
        for m in member_list[:300]:
            self.member_tree.insert('', 'end', values=(
                m.get('name', ''), m.get('card', ''), m.get('email', ''),
                m.get('phone', ''), m.get('device_id', '')))
        self._set_member_count(min(len(member_list), 300), len(member_list))

        self.device_tree.delete(*self.device_tree.get_children())
        for d in device_list:
            is_primary = "Yes" if d.get('ip_address') == device_ip else "No"
            self.device_tree.insert('', 'end', values=(
                d.get('name', ''), d.get('ip_address', ''), d.get('port_no', ''), is_primary))

        if device_ip:
            self.primary_label.config(text=f"Primary device: {device_ip}:{device_port}", foreground='#28a745')
        else:
            self.primary_label.config(text="Primary device: none (add or select one)", foreground='#dc3545')

    def _set_member_count(self, shown, total):
        self.mem_count_label.config(text=f"Showing {shown} of {total}")

    def search_members(self):
        q = self.mem_search.get().lower()
        self.member_tree.delete(*self.member_tree.get_children())
        shown = 0
        for m in member_list:
            hay = f"{m.get('name','')} {m.get('card','')} {m.get('email','')} {m.get('phone','')}".lower()
            if q and q not in hay:
                continue
            if not q and shown >= 300:
                break
            self.member_tree.insert('', 'end', values=(
                m.get('name', ''), m.get('card', ''), m.get('email', ''),
                m.get('phone', ''), m.get('device_id', '')))
            shown += 1
        self._set_member_count(shown, len(member_list))

    # -- device selection -------------------------------------------------
    def add_manual_device(self):
        global device_list, device_ip, device_port, device_password
        name = self.dev_name_entry.get().strip() or 'Manual Device'
        ip = self.dev_ip_entry.get().strip()
        if not ip:
            messagebox.showwarning("Warning", "IP address is required")
            return
        try:
            port = int(self.dev_port_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Warning", "Port must be a number")
            return
        try:
            password = int(self.dev_pw_entry.get().strip() or 0)
        except ValueError:
            messagebox.showwarning("Warning", "Comm Key must be a number")
            return

        device_list = [d for d in device_list if d.get('ip_address') != ip]
        device_list.append({'name': name, 'ip_address': ip, 'port_no': port, 'org': org_id})
        save_device_config(ip, port, password)
        device_ip, device_port, device_password = ip, port, password
        self.dev_name_entry.delete(0, 'end')
        self.dev_ip_entry.delete(0, 'end')
        self.update_dashboard_data()
        messagebox.showinfo("Success", f"Added and set primary device {ip}:{port}")

    def set_primary_device(self):
        global device_ip, device_port, device_password
        sel = self.device_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Please select a device first")
            return
        vals = self.device_tree.item(sel[0])['values']
        ip, port = vals[1], vals[2]
        try:
            device_password = int(self.dev_pw_entry.get().strip() or 0)
        except (ValueError, AttributeError):
            device_password = device_password or 0
        save_device_config(ip, port, device_password)
        device_ip, device_port = ip, port
        messagebox.showinfo("Success", f"Primary device set to {ip}:{port}")
        self.update_dashboard_data()

    # -- device operations (each runs in a COM-initialised thread) --------
    def _require_device(self):
        if not device_ip:
            messagebox.showerror("Error", "No primary device configured")
            return False
        return True

    def _msg(self, kind, title, message):
        self.controller.message_queue.put(('messagebox', kind, {'title': title, 'message': message}))

    def check_connection(self):
        if not self._require_device():
            return

        @com_thread
        def work():
            dev = ZKDevice(device_ip, device_port, device_password)
            try:
                dev.connect()
                self._msg('showinfo', 'Success', 'Connection successful!')
            except Exception as e:
                self._msg('showerror', 'Error', f"Connection failed: {e}")
            finally:
                dev.disconnect()

        threading.Thread(target=work, daemon=True).start()

    def pull_data(self):
        if not self._require_device():
            return

        @com_thread
        def work():
            dev = ZKDevice(device_ip, device_port, device_password)
            try:
                dev.connect()
                records = dev.get_attendance()
                if not records:
                    self._msg('showinfo', 'Info', 'No attendance records found')
                    return
                total, success = len(records), 0
                by_devid = {}
                for m in member_list:
                    by_devid.setdefault(str(m.get('device_id')), m)
                for enroll, ts in records:
                    m = by_devid.get(str(enroll))
                    if not m:
                        continue
                    try:
                        r = requests.post(f"{API_BASE}/createAttendance",
                                          data={'scanned_time': ts, 'mem': m['id'], 'org': m['org']},
                                          timeout=REQUEST_TIMEOUT)
                        if r.status_code == 200:
                            success += 1
                    except Exception:
                        pass
                dev.clear_attendance()
                self._msg('showinfo', 'Success', f"Pulled {success} of {total} records successfully")
            except Exception as e:
                self._msg('showerror', 'Error', f"Failed to pull data: {e}")
            finally:
                dev.disconnect()

        threading.Thread(target=work, daemon=True).start()

    def sync_members(self):
        if not self._require_device():
            return

        @com_thread
        def work():
            global member_list
            dev = ZKDevice(device_ip, device_port, device_password)
            try:
                dev.connect()
                users = dev.get_users()
                device_ids = {str(u['uid']) for u in users}
                server_ids = {str(m.get('device_id')) for m in member_list}

                added = 0
                for m in member_list:
                    if str(m.get('device_id')) and str(m.get('device_id')) not in device_ids:
                        try:
                            dev.set_user(uid=m['device_id'], name=m['name'],
                                         card=int(m['card']) if str(m.get('card', '')).isdigit() else 0)
                            added += 1
                        except Exception:
                            pass

                deleted = 0
                for u in users:
                    if str(u['uid']) not in server_ids:
                        try:
                            dev.delete_user(u['uid'])
                            deleted += 1
                        except Exception:
                            pass

                member_list = [m for m in requests.get(f"{API_BASE}/member", timeout=REQUEST_TIMEOUT).json()
                               if m.get('org') == org_id]
                self.controller.message_queue.put(('method', self, 'update_dashboard_data', [], {}))
                self._msg('showinfo', 'Success', f"Synced members: Added {added}, Deleted {deleted}")
            except Exception as e:
                self._msg('showerror', 'Error', f"Failed to sync members: {e}")
            finally:
                dev.disconnect()

        threading.Thread(target=work, daemon=True).start()

    def restart_device(self):
        if not self._require_device():
            return
        if not messagebox.askyesno("Confirm", "Restart the device?"):
            return

        @com_thread
        def work():
            dev = ZKDevice(device_ip, device_port, device_password)
            try:
                dev.connect()
                dev.restart()
                self._msg('showinfo', 'Success', 'Device is restarting')
            except Exception as e:
                self._msg('showerror', 'Error', f"Failed to restart device: {e}")
            finally:
                dev.disconnect()

        threading.Thread(target=work, daemon=True).start()

    def power_off(self):
        if not self._require_device():
            return
        if not messagebox.askyesno("Confirm", "Power off the device?"):
            return

        @com_thread
        def work():
            dev = ZKDevice(device_ip, device_port, device_password)
            try:
                dev.connect()
                dev.poweroff()
                self._msg('showinfo', 'Success', 'Device is powering off')
            except Exception as e:
                self._msg('showerror', 'Error', f"Failed to power off device: {e}")
            finally:
                dev.disconnect()

        threading.Thread(target=work, daemon=True).start()

    def refresh_data(self):
        @com_thread
        def work():
            global member_list, classification_list, device_list
            try:
                member_list = [m for m in requests.get(f"{API_BASE}/member", timeout=REQUEST_TIMEOUT).json()
                               if m.get('org') == org_id]
                classification_list = [c for c in requests.get(f"{API_BASE}/classification", timeout=REQUEST_TIMEOUT).json()
                                       if c.get('org') == org_id]
                device_list = [d for d in requests.get(f"{API_BASE}/device", timeout=REQUEST_TIMEOUT).json()
                               if d.get('org') == org_id]
                self.controller.message_queue.put(('method', self, 'update_dashboard_data', [], {}))
                self._msg('showinfo', 'Success', 'Data refreshed successfully')
            except Exception as e:
                self._msg('showerror', 'Error', f"Failed to refresh data: {e}")

        threading.Thread(target=work, daemon=True).start()

    # -- live scan (real-time SDK events) ---------------------------------
    def toggle_live_scan(self):
        if self.scanning:
            self.scanning = False
            self.scan_btn.config(text="Start Live Scan", style='Success.TButton')
            self.live_status.config(text="Status: Stopping...", foreground='#6c757d')
        else:
            if not self._require_device():
                return
            self.scanning = True
            self.scan_btn.config(text="Stop Live Scan", style='Danger.TButton')
            self.live_status.config(text="Status: Connecting...", foreground='#17a2b8')
            threading.Thread(target=com_thread(self._live_thread), daemon=True).start()

    def _live_thread(self):
        by_devid = {str(m.get('device_id')): m for m in member_list}

        def on_transaction(EnrollNumber, *args):
            m = by_devid.get(str(EnrollNumber))
            now = datetime.datetime.now().strftime("%H:%M:%S")
            if m:
                self.log_message(f"{m['name']} scanned at {now}")
            else:
                self.log_message(f"Unknown user (ID: {EnrollNumber}) at {now}", warning=True)

        try:
            zk = win32com.client.Dispatch("zkemkeeper.ZKEM")
            if device_password:
                try:
                    zk.SetCommPassword(int(device_password))
                except Exception:
                    pass
            if not zk.Connect_Net(device_ip, int(device_port)):
                raise Exception("Connect_Net failed")

            # Try to subscribe to real-time events. Requires the SDK typelib;
            # if event binding is unavailable, fall back to a clear message.
            handler_ok = False
            try:
                events = win32com.client.WithEvents(zk, _LiveEventSink)
                events.callback = on_transaction
                zk.RegEvent(ZKDevice.MACHINE, 65535)
                handler_ok = True
            except Exception as ev_err:
                self.log_message(f"Live events unavailable: {ev_err}", warning=True)

            self.controller.message_queue.put(('method', self.live_status, 'config', [],
                                               {'text': f"Status: Scanning on {device_ip}", 'foreground': '#28a745'}))
            self.log_message(f"Connected to {device_ip}:{device_port}")

            while self.scanning:
                if handler_ok:
                    pythoncom.PumpWaitingMessages()
                import time
                time.sleep(0.2)

            try:
                zk.Disconnect()
            except Exception:
                pass
        except Exception as e:
            self.log_message(f"Live scan error: {e}", error=True)
        finally:
            self.scanning = False
            self.controller.message_queue.put(('method', self.scan_btn, 'config', [],
                                               {'text': 'Start Live Scan', 'style': 'Success.TButton'}))
            self.controller.message_queue.put(('method', self.live_status, 'config', [],
                                               {'text': 'Status: Ready', 'foreground': '#6c757d'}))

    def log_message(self, message, error=False, warning=False):
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        def append():
            self.live_logs.config(state='normal')
            self.live_logs.insert('end', f"[{ts}] {message}\n")
            if error:
                self.live_logs.tag_add('e', 'end-2c linestart', 'end-2c lineend')
                self.live_logs.tag_config('e', foreground='red')
            elif warning:
                self.live_logs.tag_add('w', 'end-2c linestart', 'end-2c lineend')
                self.live_logs.tag_config('w', foreground='orange')
            self.live_logs.see('end')
            self.live_logs.config(state='disabled')

        self.controller.message_queue.put(('method', self, '_append_log', [append], {}))

    def _append_log(self, fn):
        fn()

    def clear_logs(self):
        self.live_logs.config(state='normal')
        self.live_logs.delete('1.0', 'end')
        self.live_logs.config(state='disabled')


class _LiveEventSink:
    """COM event sink for zkemkeeper real-time attendance events."""
    callback = None

    def OnAttTransactionEx(self, EnrollNumber, IsInValid, AttState, VerifyMethod,
                           Year, Month, Day, Hour, Minute, Second, WorkCode):
        if self.callback:
            try:
                self.callback(EnrollNumber)
            except Exception:
                pass


if __name__ == "__main__":
    app = PullerApp()
    app.mainloop()
