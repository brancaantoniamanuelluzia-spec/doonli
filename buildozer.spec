[app]

# Título da aplicação
title = DoOn Li

# Nome do pacote (sem espaços, minúsculas)
package.name = doonli

# Domínio do pacote
package.domain = org.doonli

# Pasta com o código fonte
source.dir = .

# Extensões de ficheiros a incluir
source.include_exts = py,png,jpg,jpeg,kv,atlas,db

# Versão da aplicação
version = 1.0

# Dependências Python necessárias
requirements = python3,kivy==2.3.0,kivymd==1.1.1,sqlite3

# Imagem do ícone (opcional — coloca um icon.png na pasta)
# icon.filename = %(source.dir)s/icon.png

# Orientação do ecrã
orientation = portrait

# Ficheiro principal
entrypoint = main.py

# ── Android ──────────────────────────────────────────────────

# Permissões Android necessárias
android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,INTERNET,VIBRATE

# Versão do Android SDK alvo
android.api = 33

# Versão mínima do Android suportada (Android 5.0+)
android.minapi = 21

# NDK versão
android.ndk = 25b

# Arquitecturas suportadas
android.archs = arm64-v8a, armeabi-v7a

# Aceitar automaticamente as licenças Android SDK
android.accept_sdk_license = True

# Funcionalidades Android
android.features = android.hardware.camera,android.hardware.location.gps

# ── Buildozer ─────────────────────────────────────────────────

# Nível de log (2 = verbose, útil para debug)
log_level = 2

# Aviso: não alteres o que está abaixo a não ser que saibas o que estás a fazer
warn_on_root = 1
