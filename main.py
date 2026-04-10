"""
DoOn Li - Sistema de Segurança para Dispositivos Android
APK feito em Python com Kivy/KivyMD
Funciona OFFLINE - dados locais com SQLite + sync Firebase quando online
"""

import os
import sys
import json
import sqlite3
import hashlib
import threading
import time
from datetime import datetime

# Kivy config ANTES dos imports
os.environ['KIVY_NO_ENV_CONFIG'] = '1'

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition, NoTransition
from kivy.core.window import Window
from kivy.utils import platform
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty, NumericProperty

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.snackbar import Snackbar

# Imports condicionais para Android
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from android import mActivity
    from jnius import autoclass

# ─── BASE DE DADOS LOCAL (OFFLINE) ─────────────────────────────────────────────

DB_PATH = 'doonli.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS security_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_primary_hash TEXT NOT NULL,
            code_secondary_hash TEXT NOT NULL,
            code_master_hash TEXT NOT NULL,
            alert_sound TEXT DEFAULT 'sirene',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS intrusion_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            photo_path TEXT,
            attempt_code TEXT,
            location_lat REAL,
            location_lon REAL
        );

        CREATE TABLE IF NOT EXISTS device_location (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lat REAL,
            lon REAL,
            accuracy REAL,
            battery INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS remote_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            command TEXT,
            payload TEXT,
            executed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()

def get_db():
    return sqlite3.connect(DB_PATH)

# ─── GERENCIADOR DE SESSÃO ──────────────────────────────────────────────────────

class SessionManager:
    _user_id = None
    _email = None
    _name = None
    _codes_configured = False

    @classmethod
    def login(cls, user_id, email, name):
        cls._user_id = user_id
        cls._email = email
        cls._name = name

    @classmethod
    def get_user_id(cls):
        return cls._user_id

    @classmethod
    def is_logged(cls):
        return cls._user_id is not None

    @classmethod
    def logout(cls):
        cls._user_id = None
        cls._email = None
        cls._name = None
        cls._codes_configured = False

# ─── SERVIÇO GPS (ANDROID) ──────────────────────────────────────────────────────

class GPSService:
    def __init__(self):
        self.lat = None
        self.lon = None
        self.running = False

    def start(self):
        if platform == 'android':
            self._start_android_gps()
        else:
            # Simulação em desktop
            self.lat = -8.8390
            self.lon = 13.2894
            print("[GPS] Modo simulação: Luanda, Angola")

    def _start_android_gps(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.CAMERA,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ])
            # Inicia localização via Android API
            Context = autoclass('android.content.Context')
            LocationManager = autoclass('android.location.LocationManager')
            activity = mActivity
            lm = activity.getSystemService(Context.LOCATION_SERVICE)
            location = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            if location:
                self.lat = location.getLatitude()
                self.lon = location.getLongitude()
        except Exception as e:
            print(f"[GPS] Erro: {e}")

    def get_location(self):
        return self.lat, self.lon

    def save_location(self, user_id):
        if self.lat and self.lon:
            conn = get_db()
            c = conn.cursor()
            c.execute("""
                INSERT INTO device_location (user_id, lat, lon, timestamp)
                VALUES (?, ?, ?, ?)
            """, (user_id, self.lat, self.lon, datetime.now().isoformat()))
            conn.commit()
            conn.close()

gps_service = GPSService()

# ─── SERVIÇO DE ALARME ──────────────────────────────────────────────────────────

class AlarmService:
    def __init__(self):
        self.active = False

    def trigger(self, sound_name='sirene'):
        self.active = True
        if platform == 'android':
            self._android_alarm(sound_name)
        else:
            print(f"[ALARME] 🚨 ALARME DISPARADO! Som: {sound_name}")

    def _android_alarm(self, sound_name):
        try:
            RingtoneManager = autoclass('android.media.RingtoneManager')
            Uri = autoclass('android.net.Uri')
            activity = mActivity
            uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ringtone = RingtoneManager.getRingtone(activity, uri)
            ringtone.play()
            self.active = True
        except Exception as e:
            print(f"[ALARME] Erro ao tocar: {e}")

    def stop(self):
        self.active = False

alarm_service = AlarmService()

# ─── SERVIÇO DE CÂMERA (CAPTURA INTRUSO) ───────────────────────────────────────

class CameraService:
    def capture_intruder(self, user_id):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        photo_path = f'intruder_{user_id}_{timestamp}.jpg'

        if platform == 'android':
            self._android_capture(photo_path, user_id)
        else:
            print(f"[CÂMERA] 📸 Foto capturada: {photo_path}")
            self._save_log(user_id, photo_path)

        return photo_path

    def _android_capture(self, photo_path, user_id):
        try:
            Camera = autoclass('android.hardware.Camera')
            cam = Camera.open(1)  # Câmera frontal
            # Lógica de captura Android
            self._save_log(user_id, photo_path)
            cam.release()
        except Exception as e:
            print(f"[CÂMERA] Erro: {e}")
            self._save_log(user_id, 'no_photo')

    def _save_log(self, user_id, photo_path):
        lat, lon = gps_service.get_location()
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO intrusion_logs (user_id, photo_path, location_lat, location_lon, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, photo_path, lat, lon, datetime.now().isoformat()))
        conn.commit()
        conn.close()

camera_service = CameraService()

# ─── SERVIÇO DE SYNC FIREBASE (QUANDO ONLINE) ──────────────────────────────────

class FirebaseSync:
    BASE_URL = "https://doonli-api.onrender.com/api"  # URL do backend Node.js

    def sync_location(self, user_id, lat, lon):
        """Envia localização ao servidor quando há internet"""
        def _sync():
            try:
                import urllib.request
                import urllib.parse
                data = json.dumps({
                    'user_id': user_id,
                    'lat': lat,
                    'lon': lon,
                    'timestamp': datetime.now().isoformat()
                }).encode()
                req = urllib.request.Request(
                    f"{self.BASE_URL}/location/update",
                    data=data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                urllib.request.urlopen(req, timeout=5)
                print("[SYNC] Localização enviada ao servidor")
            except Exception as e:
                print(f"[SYNC] Offline - guardado localmente: {e}")

        threading.Thread(target=_sync, daemon=True).start()

    def check_remote_commands(self, user_id):
        """Verifica se há comandos remotos (apagar dados, piscar, etc.)"""
        def _check():
            try:
                import urllib.request
                url = f"{self.BASE_URL}/commands/{user_id}"
                req = urllib.request.Request(url, method='GET')
                response = urllib.request.urlopen(req, timeout=5)
                commands = json.loads(response.read())
                for cmd in commands:
                    self._execute_command(cmd)
            except Exception:
                pass  # Offline - OK

        threading.Thread(target=_check, daemon=True).start()

    def _execute_command(self, cmd):
        action = cmd.get('command')
        if action == 'flash':
            Clock.schedule_once(lambda dt: self._flash_screen(), 0)
        elif action == 'alarm':
            alarm_service.trigger()
        elif action == 'wipe':
            self._wipe_device()
        elif action == 'sms_display':
            Clock.schedule_once(lambda dt: self._show_sms(cmd.get('payload', '')), 0)

    def _flash_screen(self):
        Window.clearcolor = (1, 1, 1, 1)
        def restore(dt):
            Window.clearcolor = (0.05, 0.05, 0.1, 1)
        Clock.schedule_interval(lambda dt: Window.clearcolor.__setitem__(
            slice(None), (1, 1, 1, 1) if Window.clearcolor[0] < 0.5 else (0.05, 0.05, 0.1, 1)
        ), 0.2)
        Clock.schedule_once(lambda dt: Clock.unschedule(lambda: None), 10)

    def _wipe_device(self):
        # Apagar dados locais
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM users")
        c.execute("DELETE FROM security_codes")
        c.execute("DELETE FROM intrusion_logs")
        c.execute("DELETE FROM device_location")
        conn.commit()
        conn.close()
        print("[WIPE] Todos os dados apagados remotamente")

firebase_sync = FirebaseSync()

# ─── SCREENS ────────────────────────────────────────────────────────────────────

KV = """
#:import SlideTransition kivy.uix.screenmanager.SlideTransition
#:import NoTransition kivy.uix.screenmanager.NoTransition
#:import MDColors kivymd.color_definitions

<RootManager>:
    SplashScreen:
        name: 'splash'
    LoginScreen:
        name: 'login'
    RegisterScreen:
        name: 'register'
    CodePrimaryScreen:
        name: 'code_primary'
    CodeSecondaryScreen:
        name: 'code_secondary'
    CodeMasterScreen:
        name: 'code_master'
    SoundPickerScreen:
        name: 'sound_picker'
    HomeScreen:
        name: 'home'
    LockScreen:
        name: 'lock'

<SplashScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        MDBoxLayout:
            orientation: 'vertical'
            size_hint_y: 0.7
            pos_hint: {'center_x': 0.5, 'center_y': 0.5}
            spacing: dp(16)
            MDBoxLayout:
                size_hint: None, None
                size: dp(100), dp(100)
                pos_hint: {'center_x': 0.5}
                md_bg_color: 0.1, 0.45, 0.85, 1
                radius: [20]
                MDLabel:
                    text: "DL"
                    font_size: "36sp"
                    bold: True
                    halign: 'center'
                    theme_text_color: 'Custom'
                    text_color: 1, 1, 1, 1
            MDLabel:
                text: "DoOn Li"
                font_size: "32sp"
                bold: True
                halign: 'center'
                theme_text_color: 'Custom'
                text_color: 1, 1, 1, 1
            MDLabel:
                text: "SEGURANÇA INTELIGENTE"
                font_size: "12sp"
                halign: 'center'
                theme_text_color: 'Custom'
                text_color: 0.4, 0.65, 0.9, 1
            MDLabel:
                text: "Proteja · Rastreie · Recupere"
                font_size: "11sp"
                halign: 'center'
                theme_text_color: 'Custom'
                text_color: 0.35, 0.45, 0.55, 1
        MDBoxLayout:
            orientation: 'vertical'
            padding: dp(32)
            spacing: dp(12)
            size_hint_y: 0.3
            MDRaisedButton:
                text: "COMEÇAR"
                md_bg_color: 0.1, 0.45, 0.85, 1
                size_hint_x: 1
                height: dp(50)
                on_release: app.go_to_login()
            MDLabel:
                text: "v1.0 · DoOn Li Security"
                font_size: "10sp"
                halign: 'center'
                theme_text_color: 'Custom'
                text_color: 0.3, 0.35, 0.4, 1

<LoginScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(32)
        spacing: dp(16)
        MDLabel:
            text: "Bem-vindo"
            font_size: "28sp"
            bold: True
            size_hint_y: None
            height: dp(40)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDLabel:
            text: "Inicia sessão ou cria a tua conta DoOn Li"
            font_size: "13sp"
            size_hint_y: None
            height: dp(30)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDTextField:
            id: login_email
            hint_text: "Email"
            icon_left: "email"
            mode: "rectangle"
            color_mode: 'custom'
            line_color_focus: 0.1, 0.45, 0.85, 1
            hint_text_color_normal: 0.4, 0.5, 0.6, 1
        MDTextField:
            id: login_password
            hint_text: "Password"
            icon_left: "lock"
            password: True
            mode: "rectangle"
            color_mode: 'custom'
            line_color_focus: 0.1, 0.45, 0.85, 1
        MDRaisedButton:
            text: "INICIAR SESSÃO"
            md_bg_color: 0.1, 0.45, 0.85, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.do_login()
        MDFlatButton:
            text: "Continuar com Google"
            size_hint_x: 1
            height: dp(50)
            theme_text_color: 'Custom'
            text_color: 0.9, 0.9, 0.9, 1
            on_release: app.do_google_login()
        MDFlatButton:
            text: "Criar conta DoOn Li"
            size_hint_x: 1
            height: dp(44)
            theme_text_color: 'Custom'
            text_color: 0.4, 0.7, 1, 1
            on_release: app.go_to('register')
        Widget:

<RegisterScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(32)
        spacing: dp(14)
        MDLabel:
            text: "Criar Conta"
            font_size: "26sp"
            bold: True
            size_hint_y: None
            height: dp(40)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDTextField:
            id: reg_name
            hint_text: "Nome completo"
            icon_left: "account"
            mode: "rectangle"
        MDTextField:
            id: reg_email
            hint_text: "Email"
            icon_left: "email"
            mode: "rectangle"
        MDTextField:
            id: reg_password
            hint_text: "Password"
            icon_left: "lock"
            password: True
            mode: "rectangle"
        MDTextField:
            id: reg_confirm
            hint_text: "Confirmar password"
            icon_left: "lock-check"
            password: True
            mode: "rectangle"
        MDRaisedButton:
            text: "CRIAR CONTA"
            md_bg_color: 0.1, 0.45, 0.85, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.do_register()
        MDFlatButton:
            text: "Já tenho conta · Entrar"
            size_hint_x: 1
            theme_text_color: 'Custom'
            text_color: 0.4, 0.7, 1, 1
            on_release: app.go_to('login')
        Widget:

<CodePrimaryScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(24)
        spacing: dp(12)
        MDLabel:
            text: "🛡️ Código Principal"
            font_size: "22sp"
            bold: True
            halign: 'center'
            size_hint_y: None
            height: dp(44)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDLabel:
            text: "Passo 1 de 3"
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(20)
            theme_text_color: 'Custom'
            text_color: 0.3, 0.6, 1, 1
        MDLabel:
            text: "Este código será pedido ao desbloquear o ecrã e ao entrar no DoOn Li."
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(40)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDTextField:
            id: code1
            hint_text: "Criar código (mín. 4 dígitos)"
            icon_left: "numeric"
            password: True
            input_filter: 'int'
            mode: "rectangle"
        MDTextField:
            id: code1_confirm
            hint_text: "Confirmar código"
            icon_left: "numeric-check"
            password: True
            input_filter: 'int'
            mode: "rectangle"
        MDRaisedButton:
            text: "PRÓXIMO →"
            md_bg_color: 0.1, 0.45, 0.85, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.save_code_primary()
        Widget:

<CodeSecondaryScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(24)
        spacing: dp(12)
        MDLabel:
            text: "🔑 Código Secundário"
            font_size: "22sp"
            bold: True
            halign: 'center'
            size_hint_y: None
            height: dp(44)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDLabel:
            text: "Passo 2 de 3"
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(20)
            theme_text_color: 'Custom'
            text_color: 0.9, 0.7, 0.2, 1
        MDLabel:
            text: "Use este código se esquecer o principal. Permite desbloquear e entrar no DoOn Li."
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(40)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDTextField:
            id: code2
            hint_text: "Código secundário (diferente do principal)"
            icon_left: "key"
            password: True
            input_filter: 'int'
            mode: "rectangle"
        MDTextField:
            id: code2_confirm
            hint_text: "Confirmar código secundário"
            icon_left: "key-change"
            password: True
            input_filter: 'int'
            mode: "rectangle"
        MDRaisedButton:
            text: "PRÓXIMO →"
            md_bg_color: 0.9, 0.65, 0.1, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.save_code_secondary()
        Widget:

<CodeMasterScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(24)
        spacing: dp(12)
        MDLabel:
            text: "👑 Código Master"
            font_size: "22sp"
            bold: True
            halign: 'center'
            size_hint_y: None
            height: dp(44)
            theme_text_color: 'Custom'
            text_color: 1, 0.85, 0.2, 1
        MDLabel:
            text: "Passo 3 de 3 — O mais importante!"
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(20)
            theme_text_color: 'Custom'
            text_color: 1, 0.7, 0.1, 1
        MDLabel:
            text: "Recuperação total. Se esquecer todos os códigos, este desbloqueia tudo. GUARDE-O EM LUGAR SEGURO."
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(50)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDTextField:
            id: code3
            hint_text: "Código master (único e secreto)"
            icon_left: "crown"
            password: True
            mode: "rectangle"
        MDTextField:
            id: code3_confirm
            hint_text: "Confirmar código master"
            icon_left: "crown-outline"
            password: True
            mode: "rectangle"
        MDLabel:
            text: "⚠️ Recuperação por email cadastrado caso perca este código"
            font_size: "11sp"
            halign: 'center'
            size_hint_y: None
            height: dp(36)
            theme_text_color: 'Custom'
            text_color: 1, 0.6, 0.1, 1
        MDRaisedButton:
            text: "CONCLUIR CONFIGURAÇÃO ✓"
            md_bg_color: 0.85, 0.6, 0.05, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.save_code_master()
        Widget:

<SoundPickerScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        padding: dp(24)
        spacing: dp(10)
        MDLabel:
            text: "🔊 Som de Alerta"
            font_size: "22sp"
            bold: True
            halign: 'center'
            size_hint_y: None
            height: dp(44)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDLabel:
            text: "Escolha o alarme que toca quando alguém erra o código"
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(36)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        ScrollView:
            MDList:
                id: sound_list
                padding: 0
        MDRaisedButton:
            text: "CONFIRMAR E ACTIVAR ✓"
            md_bg_color: 0.15, 0.7, 0.35, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.save_sound()
        Widget:
            size_hint_y: None
            height: dp(20)

<HomeScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.05, 0.05, 0.12, 1
        MDTopAppBar:
            title: "DoOn Li"
            md_bg_color: 0.07, 0.1, 0.2, 1
            specific_text_color: 1, 1, 1, 1
            right_action_items: [["shield-check", lambda x: app.show_status()], ["logout", lambda x: app.do_logout()]]
        ScrollView:
            MDBoxLayout:
                orientation: 'vertical'
                padding: dp(20)
                spacing: dp(14)
                size_hint_y: None
                height: self.minimum_height
                MDCard:
                    orientation: 'vertical'
                    padding: dp(16)
                    spacing: dp(8)
                    size_hint_y: None
                    height: dp(120)
                    md_bg_color: 0.07, 0.15, 0.3, 1
                    radius: [12]
                    MDLabel:
                        text: "🛡️ Sistema Activo"
                        font_size: "18sp"
                        bold: True
                        theme_text_color: 'Custom'
                        text_color: 0.4, 0.8, 1, 1
                    MDLabel:
                        id: home_status
                        text: "Protegido · GPS activo · Alarme configurado"
                        font_size: "12sp"
                        theme_text_color: 'Custom'
                        text_color: 0.6, 0.75, 0.9, 1
                    MDLabel:
                        id: home_location
                        text: "📍 A obter localização..."
                        font_size: "11sp"
                        theme_text_color: 'Custom'
                        text_color: 0.4, 0.6, 0.75, 1
                MDLabel:
                    text: "Acções rápidas"
                    font_size: "14sp"
                    bold: True
                    size_hint_y: None
                    height: dp(30)
                    theme_text_color: 'Custom'
                    text_color: 0.7, 0.8, 0.9, 1
                MDBoxLayout:
                    spacing: dp(10)
                    size_hint_y: None
                    height: dp(100)
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(12)
                        md_bg_color: 0.1, 0.2, 0.35, 1
                        radius: [10]
                        on_release: app.show_intrusion_logs()
                        MDLabel:
                            text: "📸"
                            font_size: "28sp"
                            halign: 'center'
                        MDLabel:
                            text: "Capturas"
                            font_size: "11sp"
                            halign: 'center'
                            theme_text_color: 'Custom'
                            text_color: 0.7, 0.85, 1, 1
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(12)
                        md_bg_color: 0.1, 0.2, 0.35, 1
                        radius: [10]
                        on_release: app.update_location()
                        MDLabel:
                            text: "📍"
                            font_size: "28sp"
                            halign: 'center'
                        MDLabel:
                            text: "Localização"
                            font_size: "11sp"
                            halign: 'center'
                            theme_text_color: 'Custom'
                            text_color: 0.7, 0.85, 1, 1
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(12)
                        md_bg_color: 0.25, 0.08, 0.08, 1
                        radius: [10]
                        on_release: app.test_alarm()
                        MDLabel:
                            text: "🚨"
                            font_size: "28sp"
                            halign: 'center'
                        MDLabel:
                            text: "Testar"
                            font_size: "11sp"
                            halign: 'center'
                            theme_text_color: 'Custom'
                            text_color: 1, 0.6, 0.6, 1
                MDLabel:
                    text: "Tentativas de intrusão"
                    font_size: "14sp"
                    bold: True
                    size_hint_y: None
                    height: dp(30)
                    theme_text_color: 'Custom'
                    text_color: 0.7, 0.8, 0.9, 1
                MDCard:
                    id: intrusion_card
                    orientation: 'vertical'
                    padding: dp(14)
                    spacing: dp(6)
                    size_hint_y: None
                    height: dp(80)
                    md_bg_color: 0.08, 0.1, 0.18, 1
                    radius: [10]
                    MDLabel:
                        id: intrusion_count
                        text: "0 tentativas registadas"
                        font_size: "13sp"
                        theme_text_color: 'Custom'
                        text_color: 0.5, 0.65, 0.8, 1
                    MDLabel:
                        text: "Aceda ao site Find my DoOn Li para mais detalhes"
                        font_size: "10sp"
                        theme_text_color: 'Custom'
                        text_color: 0.35, 0.45, 0.55, 1

<LockScreen>:
    MDBoxLayout:
        orientation: 'vertical'
        md_bg_color: 0.03, 0.03, 0.08, 1
        padding: dp(32)
        spacing: dp(20)
        Widget:
            size_hint_y: 0.15
        MDLabel:
            text: "DoOn Li"
            font_size: "14sp"
            halign: 'center'
            size_hint_y: None
            height: dp(24)
            theme_text_color: 'Custom'
            text_color: 0.3, 0.5, 0.75, 1
        MDLabel:
            id: lock_time
            text: "00:00"
            font_size: "52sp"
            bold: True
            halign: 'center'
            size_hint_y: None
            height: dp(70)
            theme_text_color: 'Custom'
            text_color: 1, 1, 1, 1
        MDLabel:
            id: lock_date
            text: ""
            font_size: "14sp"
            halign: 'center'
            size_hint_y: None
            height: dp(24)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDLabel:
            id: sms_display
            text: ""
            font_size: "12sp"
            halign: 'center'
            size_hint_y: None
            height: dp(60)
            theme_text_color: 'Custom'
            text_color: 0.4, 0.8, 1, 1
        Widget:
        MDLabel:
            text: "Inserir código de desbloqueio"
            font_size: "13sp"
            halign: 'center'
            size_hint_y: None
            height: dp(28)
            theme_text_color: 'Custom'
            text_color: 0.5, 0.65, 0.8, 1
        MDTextField:
            id: unlock_code
            hint_text: "● ● ● ● ● ●"
            password: True
            input_filter: 'int'
            halign: 'center'
            mode: "rectangle"
            on_text_validate: app.try_unlock()
        MDRaisedButton:
            text: "DESBLOQUEAR"
            md_bg_color: 0.1, 0.35, 0.7, 1
            size_hint_x: 1
            height: dp(50)
            on_release: app.try_unlock()
        MDFlatButton:
            text: "Esqueci os códigos · Recuperar"
            size_hint_x: 1
            theme_text_color: 'Custom'
            text_color: 0.4, 0.6, 0.85, 1
            on_release: app.recover_code()
        Widget:
            size_hint_y: 0.1
"""


class RootManager(ScreenManager):
    pass

class SplashScreen(Screen): pass
class LoginScreen(Screen): pass
class RegisterScreen(Screen): pass
class CodePrimaryScreen(Screen): pass
class CodeSecondaryScreen(Screen): pass
class CodeMasterScreen(Screen): pass
class SoundPickerScreen(Screen): pass
class HomeScreen(Screen): pass
class LockScreen(Screen): pass


# ─── APP PRINCIPAL ──────────────────────────────────────────────────────────────

class DoOnLiApp(MDApp):
    title = "DoOn Li"
    theme_cls_primary_palette = "Blue"
    theme_cls_primary_hue = "700"

    _code_primary = ""
    _code_secondary = ""
    _code_master = ""
    _selected_sound = "sirene"

    SOUNDS = [
        ("🚨 Sirene de Emergência", "sirene"),
        ("🔔 Alarme Policial", "policia"),
        ("📢 Buzina Alta", "buzina"),
        ("⚡ Alerta Contínuo", "continuo"),
        ("🎺 Alerta Roubo", "roubo"),
    ]

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        init_db()
        gps_service.start()
        return Builder.load_string(KV)

    def on_start(self):
        Clock.schedule_interval(self._update_lock_time, 1)
        Clock.schedule_interval(self._sync_location, 60)
        Clock.schedule_interval(self._check_commands, 30)
        self._update_intrusion_count()

    def _update_lock_time(self, dt):
        try:
            lock = self.root.get_screen('lock')
            now = datetime.now()
            lock.ids.lock_time.text = now.strftime('%H:%M')
            lock.ids.lock_date.text = now.strftime('%A, %d %B %Y')
        except Exception:
            pass

    def _sync_location(self, dt):
        if SessionManager.is_logged():
            lat, lon = gps_service.get_location()
            if lat:
                firebase_sync.sync_location(SessionManager.get_user_id(), lat, lon)
                gps_service.save_location(SessionManager.get_user_id())
                try:
                    home = self.root.get_screen('home')
                    home.ids.home_location.text = f"📍 {lat:.4f}, {lon:.4f}"
                except Exception:
                    pass

    def _check_commands(self, dt):
        if SessionManager.is_logged():
            firebase_sync.check_remote_commands(SessionManager.get_user_id())
            self._check_sms_display()

    def _check_sms_display(self):
        """Verifica se há SMS remoto para mostrar no ecrã bloqueado"""
        if not SessionManager.is_logged():
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT payload FROM remote_commands
            WHERE user_id=? AND command='sms_display' AND executed=0
            ORDER BY id DESC LIMIT 1
        """, (SessionManager.get_user_id(),))
        row = c.fetchone()
        conn.close()
        if row:
            try:
                lock = self.root.get_screen('lock')
                lock.ids.sms_display.text = f"📩 {row[0]}"
            except Exception:
                pass

    def _update_intrusion_count(self, *args):
        if not SessionManager.is_logged():
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM intrusion_logs WHERE user_id=?",
                  (SessionManager.get_user_id(),))
        count = c.fetchone()[0]
        conn.close()
        try:
            home = self.root.get_screen('home')
            home.ids.intrusion_count.text = f"{count} tentativa(s) de intrusão registada(s)"
        except Exception:
            pass

    # ─── NAVEGAÇÃO ──────────────────────────────────────────────────────────────

    def go_to(self, screen_name, direction='left'):
        self.root.transition = SlideTransition(direction=direction)
        self.root.current = screen_name

    def go_to_login(self):
        self.go_to('login')

    # ─── AUTH ───────────────────────────────────────────────────────────────────

    def do_login(self):
        screen = self.root.get_screen('login')
        email = screen.ids.login_email.text.strip()
        password = screen.ids.login_password.text.strip()

        if not email or not password:
            Snackbar(text="Preenche email e password").open()
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, name, email FROM users WHERE email=? AND password_hash=?",
                  (email, hash_code(password)))
        user = c.fetchone()
        conn.close()

        if not user:
            Snackbar(text="Email ou password incorrectos").open()
            return

        SessionManager.login(user[0], user[2], user[1])

        # Verificar se tem códigos configurados
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM security_codes WHERE user_id=?", (user[0],))
        has_codes = c.fetchone()
        conn.close()

        if has_codes:
            self.go_to('home')
        else:
            self.go_to('code_primary')

    def do_google_login(self):
        # Simulação Google OAuth
        # Em produção: usar google-auth-oauthlib ou Firebase Google Sign-In
        Snackbar(text="Google Sign-In: integra com Firebase Auth").open()

    def do_register(self):
        screen = self.root.get_screen('register')
        name = screen.ids.reg_name.text.strip()
        email = screen.ids.reg_email.text.strip()
        password = screen.ids.reg_password.text.strip()
        confirm = screen.ids.reg_confirm.text.strip()

        if not all([name, email, password, confirm]):
            Snackbar(text="Preenche todos os campos").open()
            return

        if password != confirm:
            Snackbar(text="As passwords não coincidem").open()
            return

        if len(password) < 6:
            Snackbar(text="Password deve ter pelo menos 6 caracteres").open()
            return

        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT INTO users (name, email, password_hash) VALUES (?,?,?)",
                      (name, email, hash_code(password)))
            user_id = c.lastrowid
            conn.commit()
            conn.close()

            SessionManager.login(user_id, email, name)
            self.go_to('code_primary')
        except sqlite3.IntegrityError:
            Snackbar(text="Este email já está registado").open()

    def do_logout(self):
        SessionManager.logout()
        self.go_to('login', direction='right')

    # ─── CÓDIGOS ────────────────────────────────────────────────────────────────

    def save_code_primary(self):
        screen = self.root.get_screen('code_primary')
        code = screen.ids.code1.text.strip()
        confirm = screen.ids.code1_confirm.text.strip()

        if len(code) < 4:
            Snackbar(text="Código deve ter pelo menos 4 dígitos").open()
            return
        if code != confirm:
            Snackbar(text="Os códigos não coincidem").open()
            return

        self._code_primary = code
        self.go_to('code_secondary')

    def save_code_secondary(self):
        screen = self.root.get_screen('code_secondary')
        code = screen.ids.code2.text.strip()
        confirm = screen.ids.code2_confirm.text.strip()

        if len(code) < 4:
            Snackbar(text="Código deve ter pelo menos 4 dígitos").open()
            return
        if code != confirm:
            Snackbar(text="Os códigos não coincidem").open()
            return
        if code == self._code_primary:
            Snackbar(text="O código secundário deve ser diferente do principal").open()
            return

        self._code_secondary = code
        self.go_to('code_master')

    def save_code_master(self):
        screen = self.root.get_screen('code_master')
        code = screen.ids.code3.text.strip()
        confirm = screen.ids.code3_confirm.text.strip()

        if len(code) < 4:
            Snackbar(text="Código deve ter pelo menos 4 dígitos").open()
            return
        if code != confirm:
            Snackbar(text="Os códigos não coincidem").open()
            return

        self._code_master = code

        # Guardar todos na base de dados
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO security_codes
            (user_id, code_primary_hash, code_secondary_hash, code_master_hash)
            VALUES (?,?,?,?)
        """, (
            SessionManager.get_user_id(),
            hash_code(self._code_primary),
            hash_code(self._code_secondary),
            hash_code(self._code_master)
        ))
        conn.commit()
        conn.close()

        self._populate_sound_list()
        self.go_to('sound_picker')

    def _populate_sound_list(self):
        from kivymd.uix.list import OneLineIconListItem
        from kivymd.uix.selectioncontrol import MDCheckbox

        screen = self.root.get_screen('sound_picker')
        screen.ids.sound_list.clear_widgets()

        for label, key in self.SOUNDS:
            item = OneLineIconListItem(
                text=label,
                theme_text_color='Custom',
                text_color=(0.8, 0.9, 1, 1),
                on_release=lambda x, k=key: self._select_sound(k)
            )
            screen.ids.sound_list.add_widget(item)

    def _select_sound(self, sound_key):
        self._selected_sound = sound_key
        alarm_service.trigger(sound_key)
        Snackbar(text=f"Som seleccionado: {sound_key}").open()

    def save_sound(self):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE security_codes SET alert_sound=? WHERE user_id=?",
                  (self._selected_sound, SessionManager.get_user_id()))
        conn.commit()
        conn.close()
        self.go_to('home')

    # ─── DESBLOQUEIO ────────────────────────────────────────────────────────────

    def try_unlock(self):
        screen = self.root.get_screen('lock')
        entered = screen.ids.unlock_code.text.strip()

        if not entered:
            return

        conn = get_db()
        c = conn.cursor()

        # Verificar qual utilizador está registado
        c.execute("SELECT user_id, code_primary_hash, code_secondary_hash, code_master_hash FROM security_codes LIMIT 1")
        codes = c.fetchone()
        conn.close()

        if not codes:
            self.go_to('home')
            return

        user_id, ph, sh, mh = codes
        entered_hash = hash_code(entered)

        if entered_hash in [ph, sh, mh]:
            SessionManager.login(user_id, '', '')
            screen.ids.unlock_code.text = ''
            self.go_to('home')
        else:
            # INTRUSO DETECTADO
            screen.ids.unlock_code.text = ''
            Snackbar(text="⚠️ Código errado! Alarme activado!").open()
            alarm_service.trigger(self._selected_sound)
            camera_service.capture_intruder(user_id)
            gps_service.save_location(user_id)
            firebase_sync.sync_location(user_id, *gps_service.get_location())
            self._update_intrusion_count()

    def recover_code(self):
        Snackbar(text="Email de recuperação enviado para o email cadastrado").open()

    # ─── HOME ACTIONS ───────────────────────────────────────────────────────────

    def show_status(self):
        lat, lon = gps_service.get_location()
        Snackbar(text=f"GPS: {lat:.4f}, {lon:.4f} · Sistema activo").open()

    def update_location(self):
        gps_service.start()
        lat, lon = gps_service.get_location()
        if lat:
            firebase_sync.sync_location(SessionManager.get_user_id(), lat, lon)
            try:
                home = self.root.get_screen('home')
                home.ids.home_location.text = f"📍 {lat:.4f}, {lon:.4f}"
            except Exception:
                pass
        Snackbar(text="Localização actualizada e enviada").open()

    def test_alarm(self):
        alarm_service.trigger(self._selected_sound)
        Snackbar(text="🚨 Alarme de teste activado!").open()

    def show_intrusion_logs(self):
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, photo_path, location_lat, location_lon
            FROM intrusion_logs WHERE user_id=?
            ORDER BY id DESC LIMIT 5
        """, (SessionManager.get_user_id(),))
        logs = c.fetchall()
        conn.close()

        if not logs:
            Snackbar(text="Nenhuma tentativa de intrusão registada").open()
        else:
            msg = f"{len(logs)} tentativa(s). Última: {logs[0][0][:16]}"
            Snackbar(text=msg).open()


if __name__ == '__main__':
    DoOnLiApp().run()
