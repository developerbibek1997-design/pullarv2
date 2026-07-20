import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from tkinter.font import Font
import datetime
import threading
import time
import json
import requests
from zk import ZK
from PIL import Image, ImageTk
import os
import queue
import platform
import sys


# Network timeout (seconds) used for every HTTP and device request
REQUEST_TIMEOUT = 15


def resource_path(relative_path):
    """ Get absolute path to a bundled, read-only resource (images, icon). """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_data_dir():
    """Return a persistent, user-writable directory for app config.

    This lets the app store its settings itself, so a single standalone
    executable needs no external device.json shipped alongside it.
    """
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


# Config is persisted here (created on first save) instead of a shipped file
CONFIG_PATH = os.path.join(get_data_dir(), 'device.json')


def load_device_config():
    """Load the persisted primary-device config, if any."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
            return cfg.get('ip', ''), cfg.get('port', 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return '', 0


def save_device_config(ip, port):
    """Persist the primary-device config to the user data dir."""
    with open(CONFIG_PATH, 'w') as f:
        json.dump({'ip': ip, 'port': port}, f)


# Global variables
member_list = []
classification_list = []
organization = ""
device_list = []
org_id = 0
new_member = 0
device_ip, device_port = load_device_config()

class PullerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Puller - meroattendance.com')
        self.geometry('870x500')
        self.resizable(True, True)
        self.minsize(700, 650)
        

        try:
            icon_path = resource_path('images/image.ico' if platform.system() == 'Windows' else 'images/image.png')
            if platform.system() == 'Windows':
                self.iconbitmap(icon_path)
            else:
                img = Image.open(icon_path)
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(False, photo)
        except Exception as e:
            print(f"Could not load icon: {e}")
        
        
        # Custom styling
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configure styles
        self.style.configure('.', background='#f8f9fa', font=('Segoe UI', 10))
        self.style.configure('TFrame', background='#f8f9fa')
        self.style.configure('TLabel', background='#f8f9fa')
        self.style.configure('TButton', padding=8)
        self.style.configure('Primary.TButton', foreground='white', background='#007bff')
        self.style.configure('Success.TButton', foreground='white', background='#28a745')
        self.style.configure('Danger.TButton', foreground='white', background='#dc3545')
        self.style.configure('Warning.TButton', foreground='white', background='#ffc107')
        self.style.configure('Info.TButton', foreground='white', background='#17a2b8')
        self.style.configure('TEntry', padding=6)
        self.style.configure('TProgressbar', thickness=20, background='#28a745')
        self.style.configure('Treeview', rowheight=25)
        self.style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))
        self.style.map('Treeview', background=[('selected', '#007bff')])
        
        # Create container
        self.container = ttk.Frame(self)
        self.container.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Initialize screens
        self.frames = {}
        for F in (Homepage, Dashboard):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky='nsew')
        
        self.show_frame('Homepage')
        
        # Message queue for thread-safe UI updates
        self.message_queue = queue.Queue()
        self.after(100, self.process_queue)
    
    def process_queue(self):
        """Process messages from the queue to update UI safely"""
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
        self.configure(style='Background.TFrame')
        
        # Custom styles
        self.style = ttk.Style()
        self.style.configure('Background.TFrame', background='linear-gradient(135deg, #667eea 0%, #764ba2 100%)')
        self.style.configure('Card.TFrame', background='white', borderwidth=0)
        self.style.configure('Primary.TButton', font=('Segoe UI', 10, 'bold'), 
                            foreground='white', background='#4f46e5', bordercolor='#4f46e5',
                            borderwidth=0, padding=10, focuscolor='#4f46e5')
        self.style.map('Primary.TButton', 
                    background=[('active', '#4338ca'), ('disabled', '#a5b4fc')])
        self.style.configure('TEntry', font=('Segoe UI', 10), padding=8, 
                            bordercolor='#e5e7eb', borderwidth=1, 
                            relief='flat', foreground='#1f2937')

        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Login card with modern shadow
        login_card = tk.Canvas(main_frame, bg='#f3f4f6', bd=0, highlightthickness=0)
        login_card.pack(expand=True, pady=50)
        self.draw_modern_shadow(login_card)

        inner_card = ttk.Frame(login_card, style='Card.TFrame')
        inner_card.pack(padx=20, pady=20, ipadx=40, ipady=20)

        # Logo section
        logo_frame = ttk.Frame(inner_card)
        logo_frame.pack(pady=(10, 30))
        try:
            logo_img = Image.open('images/logo.png')
            logo_img = logo_img.resize((180, 60), Image.LANCZOS)
            self.logo = ImageTk.PhotoImage(logo_img)
            logo_label = ttk.Label(logo_frame, image=self.logo)
            logo_label.pack()
        except Exception as e:
            title_label = ttk.Label(
                logo_frame, 
                text="🔐 Puller Login", 
                font=('Segoe UI', 20, 'bold'), 
                foreground='#1e40af',
                background='white'
            )
            title_label.pack()

        # Organization PIN section
        pin_frame = ttk.Frame(inner_card)
        pin_frame.pack(pady=10, padx=20, fill='x')

        ttk.Label(pin_frame, 
                text="🏢 Organization PIN:", 
                font=('Segoe UI', 11), 
                foreground='#374151',
                background='white').pack(anchor='w', pady=5)
        
        self.org_pin = ttk.Entry(pin_frame, width=30, font=('Segoe UI', 11),
                                style='TEntry', foreground='#1f2937')
        self.org_pin.pack(fill='x', ipady=6)
        self.org_pin.insert(0, 'Enter 6-digit PIN')
        self.org_pin.bind('<FocusIn>', lambda e: self.clear_placeholder())
        self.org_pin.bind('<Return>', lambda e: self.check_code())

        # Progress bar with custom style
        self.style.configure('Custom.Horizontal.TProgressbar', 
                            thickness=8, 
                            troughcolor='#e5e7eb',
                            darkcolor='#4f46e5',
                            lightcolor='#818cf8')
        self.progress = ttk.Progressbar(
            inner_card, 
            orient='horizontal', 
            mode='determinate', 
            length=300,
            style='Custom.Horizontal.TProgressbar'
        )
        self.progress.pack(pady=15, fill='x')

        # Check code button with hover effect
        self.check_btn = ttk.Button(
            inner_card, 
            text="Verify & Continue →", 
            style='Primary.TButton',
            command=self.check_code
        )
        self.check_btn.pack(pady=10, fill='x', ipady=8)

        # Status label with icon
        self.status_label = ttk.Label(
            inner_card, 
            text="", 
            foreground='#dc3545',
            font=('Segoe UI', 9),
            background='white'
        )
        self.status_label.pack(pady=(0, 15))

    def draw_modern_shadow(self, widget):
        # Create subtle layered shadow effect
        bg_color = widget.cget('bg')
        shadow_width = 4
        for i in range(shadow_width, 0, -1):
            widget.create_rectangle(
                (i, i, -i, -i), 
                outline=bg_color, 
                fill=bg_color,
                width=1
            )

    def clear_placeholder(self):
        if self.org_pin.get() == 'Enter 6-digit PIN':
            self.org_pin.delete(0, 'end')
            self.org_pin.configure(foreground='#1f2937')
    
    def draw_shadow(self, widget):
        """Create a shadow effect for the widget"""
        widget.master.configure(bg='#adb5bd')
        widget.configure(bg='#e9ecef')
        widget.update_idletasks()
        widget.master.configure(bg='#f8f9fa')
    
    def check_code(self):
        code = self.org_pin.get().strip()
        self.check_btn.config(state='disabled')
        
        if not code:
            self.show_error("Error: Puller Code is required")
            self.check_btn.config(state='normal')
            return
        
        self.progress['value'] = 5
        self.status_label.config(text="Connecting to server...")
        
        # Start a new thread to avoid freezing the UI
        threading.Thread(
            target=self.check_code_thread,
            args=(code,),
            daemon=True
        ).start()
    
    def check_code_thread(self, code):
        try:
            org_dict = self.get_organization_data()
            
            self.progress['value'] = 10
            self.status_label.config(text="Validating organization...")
            
            found = False
            for org in org_dict:
                if org['serial_key'] == code:
                    found = True
                    self.setup_organization_data(org)
                    break
            
            if not found:
                self.show_error("Invalid Puller Code")
                self.check_btn.config(state='normal')
                return
            
            # Switch to dashboard
            self.controller.show_frame('Dashboard')
            self.org_pin.delete(0, 'end')
            self.progress['value'] = 0
            self.status_label.config(text="")
            
        except Exception as e:
            self.show_error(f"Error occurred: {str(e)}")
        finally:
            self.check_btn.config(state='normal')
    
    def get_organization_data(self):
        # Simulate API call
        url = "https://www.meroattendance.com/organizationlist"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        raise Exception("Failed to fetch organization data")
    
    def setup_organization_data(self, org):
        global organization, org_id, member_list, classification_list, device_list
        
        organization = org['name']
        org_id = org['id']
        
        # Get members
        self.status_label.config(text="Fetching members...")
        self.progress['value'] = 20
        
        member_url = "https://www.meroattendance.com/member"
        member_response = requests.get(member_url, timeout=REQUEST_TIMEOUT)
        member_list = [m for m in member_response.json() if m['org'] == org_id]
        
        # Get classifications
        self.status_label.config(text="Fetching classifications...")
        self.progress['value'] = 50
        
        class_url = "https://www.meroattendance.com/classification"
        class_response = requests.get(class_url, timeout=REQUEST_TIMEOUT)
        classification_list = [c for c in class_response.json() if c['org'] == org_id]
        
        # Get devices
        self.status_label.config(text="Fetching devices...")
        self.progress['value'] = 80
        
        device_url = "https://www.meroattendance.com/device"
        device_response = requests.get(device_url, timeout=REQUEST_TIMEOUT)
        device_list = [d for d in device_response.json() if d['org'] == org_id]
        
        self.progress['value'] = 100
        self.status_label.config(text="Data loaded successfully!")
    
    def show_error(self, message):
        self.status_label.config(text=message, foreground='#dc3545')
        self.after(3000, lambda: self.status_label.config(text=""))

class Dashboard(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.configure(style='TFrame')
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)
        
        # Dashboard tab
        self.dashboard_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.dashboard_tab, text=' Dashboard ')
        
        # Members tab
        self.members_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.members_tab, text=' Members ')
        
        # Devices tab
        self.devices_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.devices_tab, text=' Devices ')
        
        # Live Attendance tab
        self.live_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.live_tab, text=' Live Attendance ')
        
        # Initialize all tabs
        self.init_dashboard_tab()
        self.init_members_tab()
        self.init_devices_tab()
        self.init_live_tab()
        
        # Bind show frame event
        self.bind('<<ShowFrame>>', self.on_show_frame)
        
        # Live scan variables
        self.scanning = False
        self.zk_conn = None
    
    def on_show_frame(self, event):
        self.update_dashboard_data()
    
    def init_dashboard_tab(self):
        # Header
        header_frame = ttk.Frame(self.dashboard_tab)
        header_frame.pack(fill='x', padx=20, pady=20)
        
        self.org_label = ttk.Label(
            header_frame, 
            text="Organization: ", 
            font=('Segoe UI', 14, 'bold')
        )
        self.org_label.pack(side='left')
        
        refresh_btn = ttk.Button(
            header_frame,
            text="Refresh Data",
            style='Info.TButton',
            command=self.refresh_data
        )
        refresh_btn.pack(side='right')
        
        # Stats frame
        stats_frame = ttk.Frame(self.dashboard_tab)
        stats_frame.pack(fill='x', padx=20, pady=10)
        
        # Member count
        mem_frame = ttk.Frame(stats_frame, style='Card.TFrame')
        mem_frame.pack(side='left', fill='both', expand=True, padx=5, ipady=10)
        ttk.Label(mem_frame, text="Total Members", font=('Segoe UI', 10)).pack(pady=(10, 5))
        self.mem_count = ttk.Label(mem_frame, text="0", font=('Segoe UI', 24, 'bold'))
        self.mem_count.pack(pady=(0, 10))
        
        # Classification count
        class_frame = ttk.Frame(stats_frame, style='Card.TFrame')
        class_frame.pack(side='left', fill='both', expand=True, padx=5, ipady=10)
        ttk.Label(class_frame, text="Total Classifications", font=('Segoe UI', 10)).pack(pady=(10, 5))
        self.class_count = ttk.Label(class_frame, text="0", font=('Segoe UI', 24, 'bold'))
        self.class_count.pack(pady=(0, 10))
        
        # Device count
        dev_frame = ttk.Frame(stats_frame, style='Card.TFrame')
        dev_frame.pack(side='left', fill='both', expand=True, padx=5, ipady=10)
        ttk.Label(dev_frame, text="Total Devices", font=('Segoe UI', 10)).pack(pady=(10, 5))
        self.dev_count = ttk.Label(dev_frame, text="0", font=('Segoe UI', 24, 'bold'))
        self.dev_count.pack(pady=(0, 10))
        
        # Buttons frame
        btn_frame = ttk.Frame(self.dashboard_tab)
        btn_frame.pack(fill='x', padx=20, pady=20)
        
        # Device controls
        ctrl_frame = ttk.LabelFrame(btn_frame, text="Device Controls", padding=10)
        ctrl_frame.pack(side='left', fill='both', expand=True, padx=5)
        
        ttk.Button(
            ctrl_frame, 
            text="Check Connection", 
            style='Info.TButton',
            command=self.check_connection
        ).pack(fill='x', pady=5)
        
        ttk.Button(
            ctrl_frame, 
            text="Pull Attendance Data", 
            style='Success.TButton',
            command=self.pull_data
        ).pack(fill='x', pady=5)
        
        ttk.Button(
            ctrl_frame, 
            text="Restart Device", 
            style='Warning.TButton',
            command=self.restart_device
        ).pack(fill='x', pady=5)
        
        ttk.Button(
            ctrl_frame, 
            text="Power Off Device", 
            style='Danger.TButton',
            command=self.power_off
        ).pack(fill='x', pady=5)
        
        # Member controls
        mem_ctrl_frame = ttk.LabelFrame(btn_frame, text="Member Controls", padding=10)
        mem_ctrl_frame.pack(side='left', fill='both', expand=True, padx=5)
        
        ttk.Button(
            mem_ctrl_frame, 
            text="Sync Members", 
            style='Primary.TButton',
            command=self.check_new_members
        ).pack(fill='x', pady=5)
        
      
        # Status frame
        status_frame = ttk.Frame(self.dashboard_tab)
        status_frame.pack(fill='x', padx=20, pady=(0, 20))
        
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            foreground='#28a745',
            font=('Segoe UI', 9)
        )
        self.status_label.pack(side='left')
    
    def init_members_tab(self):
        # Search frame
        search_frame = ttk.Frame(self.members_tab)
        search_frame.pack(fill='x', padx=20, pady=10)
        
        ttk.Label(search_frame, text="Search:").pack(side='left', padx=(0, 10))
        self.mem_search = ttk.Entry(search_frame)
        self.mem_search.pack(side='left', fill='x', expand=True)
        self.mem_search.bind('<KeyRelease>', lambda e: self.search_members())
        
        ttk.Button(
            search_frame,
            text="Clear",
            style='Danger.TButton',
            command=self.clear_search
        ).pack(side='left', padx=(10, 0))

        self.mem_count_label = ttk.Label(
            search_frame, text="", foreground='#6c757d', font=('Segoe UI', 9)
        )
        self.mem_count_label.pack(side='left', padx=(10, 0))

        # Member list frame
        list_frame = ttk.Frame(self.members_tab)
        list_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        
        # Treeview for members
        self.member_tree = ttk.Treeview(
            list_frame, 
            columns=('name', 'card', 'address', 'email', 'phone', 'gender', 'device_id'),
            show='headings',
            selectmode='extended'
        )
        
        # Configure columns
        self.member_tree.heading('name', text='Name')
        self.member_tree.heading('card', text='Card')
        self.member_tree.heading('address', text='Address')
        self.member_tree.heading('email', text='Email')
        self.member_tree.heading('phone', text='Phone')
        self.member_tree.heading('gender', text='Gender')
        self.member_tree.heading('device_id', text='Device ID')
        
        self.member_tree.column('name', width=150, anchor='w')
        self.member_tree.column('card', width=80, anchor='center')
        self.member_tree.column('address', width=150, anchor='w')
        self.member_tree.column('email', width=150, anchor='w')
        self.member_tree.column('phone', width=100, anchor='center')
        self.member_tree.column('gender', width=80, anchor='center')
        self.member_tree.column('device_id', width=80, anchor='center')
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.member_tree.yview)
        self.member_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack widgets
        self.member_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Context menu
        self.member_menu = tk.Menu(self, tearoff=0)
        self.member_menu.add_command(label="Edit Member", command=self.edit_member)
        self.member_menu.add_command(label="Delete Member", command=self.delete_member)
        self.member_tree.bind('<Button-3>', self.show_member_menu)
    
    def init_devices_tab(self):
        # Current primary device indicator
        primary_frame = ttk.Frame(self.devices_tab)
        primary_frame.pack(fill='x', padx=20, pady=(20, 0))
        self.primary_label = ttk.Label(
            primary_frame,
            text="Primary device: none",
            font=('Segoe UI', 10, 'bold'),
            foreground='#17a2b8'
        )
        self.primary_label.pack(side='left')

        # Manual add-device controls (works standalone, no shipped device.json)
        add_frame = ttk.LabelFrame(self.devices_tab, text="Add Device Manually", padding=10)
        add_frame.pack(fill='x', padx=20, pady=(10, 0))

        ttk.Label(add_frame, text="Name:").pack(side='left', padx=(0, 4))
        self.dev_name_entry = ttk.Entry(add_frame, width=14)
        self.dev_name_entry.pack(side='left', padx=(0, 10))

        ttk.Label(add_frame, text="IP:").pack(side='left', padx=(0, 4))
        self.dev_ip_entry = ttk.Entry(add_frame, width=16)
        self.dev_ip_entry.pack(side='left', padx=(0, 10))

        ttk.Label(add_frame, text="Port:").pack(side='left', padx=(0, 4))
        self.dev_port_entry = ttk.Entry(add_frame, width=8)
        self.dev_port_entry.insert(0, '4370')
        self.dev_port_entry.pack(side='left', padx=(0, 10))

        ttk.Button(
            add_frame,
            text="Add Device",
            style='Success.TButton',
            command=self.add_manual_device
        ).pack(side='left', padx=5)

        # Device list frame
        list_frame = ttk.Frame(self.devices_tab)
        list_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Treeview for devices
        self.device_tree = ttk.Treeview(
            list_frame, 
            columns=('name', 'ip', 'port', 'primary'),
            show='headings',
            selectmode='browse'
        )
        
        # Configure columns
        self.device_tree.heading('name', text='Name')
        self.device_tree.heading('ip', text='IP Address')
        self.device_tree.heading('port', text='Port')
        self.device_tree.heading('primary', text='Primary')
        
        self.device_tree.column('name', width=150, anchor='w')
        self.device_tree.column('ip', width=150, anchor='w')
        self.device_tree.column('port', width=80, anchor='center')
        self.device_tree.column('primary', width=80, anchor='center')
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack widgets
        self.device_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Controls frame
        ctrl_frame = ttk.Frame(self.devices_tab)
        ctrl_frame.pack(fill='x', padx=20, pady=(0, 20))
        
        # Set primary button
        set_primary_btn = ttk.Button(
            ctrl_frame, 
            text="Set as Primary", 
            style='Primary.TButton',
            command=self.set_primary_device
        )
        set_primary_btn.pack(side='left', fill='x', expand=True, padx=5)
        
        # Refresh devices button
        refresh_btn = ttk.Button(
            ctrl_frame,
            text="Refresh Devices",
            style='Info.TButton',
            command=self.refresh_devices
        )
        refresh_btn.pack(side='left', fill='x', expand=True, padx=5)
    
    def init_live_tab(self):
        # Live attendance frame
        live_frame = ttk.Frame(self.live_tab)
        live_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Text widget for live logs
        self.live_logs = scrolledtext.ScrolledText(
            live_frame, 
            wrap=tk.WORD, 
            font=('Consolas', 10),
            state='disabled',
            height=15
        )
        self.live_logs.pack(fill='both', expand=True)
        
        # Controls frame
        ctrl_frame = ttk.Frame(self.live_tab)
        ctrl_frame.pack(fill='x', padx=20, pady=(0, 20))
        
        self.scan_btn = ttk.Button(
            ctrl_frame, 
            text="Start Live Scan", 
            style='Success.TButton',
            command=self.toggle_live_scan
        )
        self.scan_btn.pack(side='left', fill='x', expand=True, padx=5)
        
        clear_btn = ttk.Button(
            ctrl_frame,
            text="Clear Logs",
            style='Danger.TButton',
            command=self.clear_logs
        )
        clear_btn.pack(side='left', fill='x', expand=True, padx=5)
        
        # Status frame
        status_frame = ttk.Frame(self.live_tab)
        status_frame.pack(fill='x', padx=20, pady=(0, 10))
        
        self.live_status = ttk.Label(
            status_frame,
            text="Status: Ready",
            foreground='#6c757d'
        )
        self.live_status.pack(side='left')
    
    def update_dashboard_data(self):
        global organization, member_list, classification_list, device_list
        
        self.org_label.config(text=f"Organization: {organization}")
        self.mem_count.config(text=str(len(member_list)))
        self.class_count.config(text=str(len(classification_list)))
        self.dev_count.config(text=str(len(device_list)))
        
        # Update member list
        self.member_tree.delete(*self.member_tree.get_children())
        for member in member_list[:200]:  # Show first 200 members
            self.member_tree.insert('', 'end', values=(
                member['name'],
                member['card'],
                member['address'],
                member['email'],
                member['phone'],
                member['gender'],
                member.get('device_id', '')
            ))
        self._update_member_count(min(len(member_list), 200), len(member_list))

        # Update device list
        self.device_tree.delete(*self.device_tree.get_children())
        for device in device_list:
            is_primary = "Yes" if device['ip_address'] == device_ip else "No"
            self.device_tree.insert('', 'end', values=(
                device['name'],
                device['ip_address'],
                device['port_no'],
                is_primary
            ))

        # Update primary-device indicator
        if hasattr(self, 'primary_label'):
            if device_ip:
                self.primary_label.config(
                    text=f"Primary device: {device_ip}:{device_port}",
                    foreground='#28a745'
                )
            else:
                self.primary_label.config(
                    text="Primary device: none (add or select one)",
                    foreground='#dc3545'
                )
    
    def clear_search(self):
        self.mem_search.delete(0, 'end')
        self.search_members()
    
    def search_members(self):
        query = self.mem_search.get().lower()
        self.member_tree.delete(*self.member_tree.get_children())
        
        if not query:
            # Show all members if search is empty
            for member in member_list[:200]:
                self.member_tree.insert('', 'end', values=(
                    member['name'],
                    member['card'],
                    member['address'],
                    member['email'],
                    member['phone'],
                    member['gender'],
                    member.get('device_id', '')
                ))
            self._update_member_count(min(len(member_list), 200), len(member_list))
            return

        # Search in all fields
        matches = 0
        for member in member_list:
            if (query in member['name'].lower() or
                query in member['card'].lower() or
                query in member['email'].lower() or
                query in str(member['phone']) or
                query in member['address'].lower() or
                query in member['gender'].lower()):
                self.member_tree.insert('', 'end', values=(
                    member['name'],
                    member['card'],
                    member['address'],
                    member['email'],
                    member['phone'],
                    member['gender'],
                    member.get('device_id', '')
                ))
                matches += 1
        self._update_member_count(matches, len(member_list))

    def _update_member_count(self, shown, total):
        if hasattr(self, 'mem_count_label'):
            self.mem_count_label.config(text=f"Showing {shown} of {total}")

    def show_member_menu(self, event):
        item = self.member_tree.identify_row(event.y)
        if item:
            self.member_tree.selection_set(item)
            self.member_menu.post(event.x_root, event.y_root)
    
    def edit_member(self):
        selected = self.member_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a member first")
            return
        
        # Implement member editing functionality
        messagebox.showinfo("Info", "Member editing functionality will be implemented here")
    
    def delete_member(self):
        selected = self.member_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a member first")
            return
        
        if messagebox.askyesno("Confirm", "Are you sure you want to delete the selected member(s)?"):
            # Implement member deletion functionality
            messagebox.showinfo("Info", "Member deletion functionality will be implemented here")
    
    def add_manual_device(self):
        """Add a device entered by hand and make it the primary device."""
        name = self.dev_name_entry.get().strip() or 'Manual Device'
        ip = self.dev_ip_entry.get().strip()
        port_str = self.dev_port_entry.get().strip()

        if not ip:
            messagebox.showwarning("Warning", "IP address is required")
            return
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Warning", "Port must be a number")
            return

        global device_list, device_ip, device_port
        # Avoid duplicates on the same IP
        device_list = [d for d in device_list if d.get('ip_address') != ip]
        device_list.append({
            'name': name,
            'ip_address': ip,
            'port_no': port,
            'org': org_id,
        })

        # Persist as the primary device so it works standalone
        save_device_config(ip, port)
        device_ip = ip
        device_port = port

        self.dev_name_entry.delete(0, 'end')
        self.dev_ip_entry.delete(0, 'end')
        self.update_dashboard_data()
        messagebox.showinfo("Success", f"Added and set primary device {ip}:{port}")

    def set_primary_device(self):
        selected = self.device_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a device first")
            return
        
        item = self.device_tree.item(selected[0])
        ip = item['values'][1]
        port = item['values'][2]
        
        # Save to persistent config (no shipped device.json needed)
        save_device_config(ip, port)

        global device_ip, device_port
        device_ip = ip
        device_port = port
        
        messagebox.showinfo("Success", f"Primary device set to {ip}:{port}")
        self.update_dashboard_data()
    
    def refresh_devices(self):
        def refresh():
            try:
                global device_list
                device_url = "https://www.meroattendance.com/device"
                device_response = requests.get(device_url, timeout=REQUEST_TIMEOUT)
                device_list = [d for d in device_response.json() if d['org'] == org_id]
                self.update_dashboard_data()
                self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Success', 'message': 'Devices refreshed successfully'}))
            except Exception as e:
                self.controller.message_queue.put(('messagebox', 'showerror', {'title': 'Error', 'message': f'Failed to refresh devices: {str(e)}'}))
        
        threading.Thread(target=refresh, daemon=True).start()
    
    def toggle_live_scan(self):
        if self.scanning:
            self.stop_live_scan()
        else:
            self.start_live_scan()
    
    def start_live_scan(self):
        if not device_ip:
            messagebox.showerror("Error", "No primary device configured")
            return
        
        self.scanning = True
        self.scan_btn.config(text="Stop Live Scan", style='Danger.TButton')
        self.live_status.config(text="Status: Connecting to device...", foreground='#17a2b8')
        
        threading.Thread(target=self.live_scan_thread, daemon=True).start()
    
    def stop_live_scan(self):
        self.scanning = False
        self.scan_btn.config(text="Start Live Scan", style='Success.TButton')
        self.live_status.config(text="Status: Ready", foreground='#28a745')
        
        if self.zk_conn:
            try:
                self.zk_conn.disconnect()
            except:
                pass
    
    def live_scan_thread(self):
        try:
            zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
            self.zk_conn = zk.connect()
            
            self.log_message(f"Connected to device at {device_ip}:{device_port}")
            self.live_status.config(text=f"Status: Scanning on {device_ip}", foreground='#28a745')
            
            for attendance in self.zk_conn.live_capture():
                if not self.scanning:
                    break
                
                if attendance is None:
                    continue
                
                # Process attendance
                self.process_attendance(attendance)
                
        except Exception as e:
            self.log_message(f"Error in live scan: {str(e)}", error=True)
            self.stop_live_scan()
    
    def process_attendance(self, attendance):
        contr = str(attendance)
        split_colon = contr.split(': ')
        device_id = int(split_colon[1])
        timestamp = split_colon[2]
        
        for member in member_list:
            if member['device_id'] == device_id:
                message = f"{member['name']} scanned at {timestamp}"
                self.log_message(message)
                
                # Play sound notification
                try:
                    import winsound
                    winsound.Beep(1000, 200)
                except:
                    pass
                
                break
        else:
            self.log_message(f"Unknown user (ID: {device_id}) scanned at {timestamp}", warning=True)
    
    def log_message(self, message, error=False, warning=False):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        
        self.live_logs.config(state='normal')
        self.live_logs.insert('end', log_msg + '\n')
        
        if error:
            self.live_logs.tag_add('error', 'end-2c linestart', 'end-2c lineend')
            self.live_logs.tag_config('error', foreground='red')
        elif warning:
            self.live_logs.tag_add('warning', 'end-2c linestart', 'end-2c lineend')
            self.live_logs.tag_config('warning', foreground='orange')
        
        self.live_logs.see('end')
        self.live_logs.config(state='disabled')
    
    def clear_logs(self):
        self.live_logs.config(state='normal')
        self.live_logs.delete(1.0, 'end')
        self.live_logs.config(state='disabled')
    
    def check_connection(self):
        def check():
            try:
                zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
                conn = zk.connect()
                conn.disconnect()
                self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Success', 'message': 'Connection successful!'}))
            except Exception as e:
                self.controller.message_queue.put(('messagebox', 'showerror', {'title': 'Error', 'message': f"Connection failed: {str(e)}"}))
        
        threading.Thread(target=check, daemon=True).start()
    
    def pull_data(self):
        def pull():
            try:
                zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
                conn = zk.connect()
                all_data = conn.get_attendance()
                
                if not all_data:
                    self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Info', 'message': 'No attendance records found'}))
                    return
                
                total = len(all_data)
                success = 0
                
                for data in all_data:
                    split_data = str(data).split(': ')
                    device_id = int(split_data[1])
                    date_split = split_data[2].split(' (')
                    timestamp = date_split[0]
                    
                    for member in member_list:
                        if member['device_id'] == device_id:
                            datas = {
                                'scanned_time': timestamp,
                                'mem': member['id'],
                                'org': member['org']
                            }
                            response = requests.post(
                                'https://www.meroattendance.com/createAttendance',
                                data=datas,
                                timeout=REQUEST_TIMEOUT
                            )
                            if response.status_code == 200:
                                success += 1
                            break
                
                conn.clear_attendance()
                self.controller.message_queue.put(('messagebox', 'showinfo', {
                    'title': 'Success',
                    'message': f"Pulled {success} of {total} records successfully"
                }))
                
            except Exception as e:
                self.controller.message_queue.put(('messagebox', 'showerror', {
                    'title': 'Error',
                    'message': f"Failed to pull data: {str(e)}"
                }))
        
        threading.Thread(target=pull, daemon=True).start()
    
    def restart_device(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to restart the device?"):
            def restart():
                try:
                    zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
                    conn = zk.connect()
                    conn.restart()
                    self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Success', 'message': 'Device is restarting'}))
                except Exception as e:
                    self.controller.message_queue.put(('messagebox', 'showerror', {'title': 'Error', 'message': f"Failed to restart device: {str(e)}"}))
            
            threading.Thread(target=restart, daemon=True).start()
    
    def power_off(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to power off the device?"):
            def poweroff():
                try:
                    zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
                    conn = zk.connect()
                    conn.poweroff()
                    self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Success', 'message': 'Device is powering off'}))
                except Exception as e:
                    self.controller.message_queue.put(('messagebox', 'showerror', {'title': 'Error', 'message': f"Failed to power off device: {str(e)}"}))
            
            threading.Thread(target=poweroff, daemon=True).start()
    
    def check_new_members(self):
        def check():
            try:
                global member_list
                zk = ZK(device_ip, port=int(device_port), timeout=REQUEST_TIMEOUT)
                conn = zk.connect()
                all_users = conn.get_users()
                
                device_user_ids = [user.uid for user in all_users]
                member_device_ids = [member['device_id'] for member in member_list]
                
                new_in_device = list(set(device_user_ids) - set(member_device_ids))
                new_in_server = list(set(member_device_ids) - set(device_user_ids))
                
                if not new_in_device and not new_in_server:
                    self.controller.message_queue.put(('messagebox', 'showinfo', {'title': 'Info', 'message': 'No new members found'}))
                    return
                
                # Add new members to device
                for member in member_list:
                    if member['device_id'] in new_in_server:
                        conn.set_user(
                            uid=member['device_id'],
                            name=member['name'],
                            privilege=1,
                            password='',
                            group_id='',
                            user_id='',
                            card=int(member['card'])
                        )
                
                # Delete members not in server from device
                to_delete_from_device = list(set(device_user_ids) - set(member_device_ids))
                for user in all_users:
                    if user.uid in to_delete_from_device:
                        conn.delete_user(uid=user.uid)
                
                # Refresh data
                member_url = "https://www.meroattendance.com/member"
                member_response = requests.get(member_url, timeout=REQUEST_TIMEOUT)
                member_list = [m for m in member_response.json() if m['org'] == org_id]
                
                self.controller.message_queue.put(('method', self, 'update_dashboard_data', [], {}))
                self.controller.message_queue.put(('messagebox', 'showinfo', {
                    'title': 'Success',
                    'message': f"Synced members: Added {len(new_in_server)}, Deleted {len(to_delete_from_device)}"
                }))
                
            except Exception as e:
                self.controller.message_queue.put(('messagebox', 'showerror', {
                    'title': 'Error',
                    'message': f"Failed to sync members: {str(e)}"
                }))
        
        threading.Thread(target=check, daemon=True).start()
    
    
    def refresh_data(self):
        def refresh():
            try:
                global member_list, classification_list, device_list
                
                # Get members
                member_url = "https://www.meroattendance.com/member"
                member_response = requests.get(member_url, timeout=REQUEST_TIMEOUT)
                member_list = [m for m in member_response.json() if m['org'] == org_id]
                
                # Get classifications
                class_url = "https://www.meroattendance.com/classification"
                class_response = requests.get(class_url, timeout=REQUEST_TIMEOUT)
                classification_list = [c for c in class_response.json() if c['org'] == org_id]
                
                # Get devices
                device_url = "https://www.meroattendance.com/device"
                device_response = requests.get(device_url, timeout=REQUEST_TIMEOUT)
                device_list = [d for d in device_response.json() if d['org'] == org_id]
                
                self.controller.message_queue.put(('method', self, 'update_dashboard_data', [], {}))
                self.controller.message_queue.put(('messagebox', 'showinfo', {
                    'title': 'Success',
                    'message': 'Data refreshed successfully'
                }))
                
            except Exception as e:
                self.controller.message_queue.put(('messagebox', 'showerror', {
                    'title': 'Error',
                    'message': f"Failed to refresh data: {str(e)}"
                }))
        
        threading.Thread(target=refresh, daemon=True).start()

if __name__ == "__main__":
    app = PullerApp()
    app.mainloop()