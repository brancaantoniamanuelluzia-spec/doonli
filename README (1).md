# 🛡️ DoOn Li — Sistema de Segurança Android

Aplicação Android de segurança inteligente feita com Python + Kivy/KivyMD.

## Funcionalidades

- 🔐 3 códigos de segurança (Principal, Secundário, Master)
- 📸 Captura foto do intruso ao errar o código
- 📍 Rastreio GPS em tempo real
- 🚨 Alarme sonoro configurável
- 📡 Sync com servidor quando há internet
- 💾 Funciona 100% offline com SQLite

## Tecnologias

- Python 3
- Kivy 2.3.0
- KivyMD 1.1.1
- SQLite (base de dados local)
- Firebase / Render (sync online)

## Como compilar o APK

### Opção 1 — GitHub Actions (recomendado)

Faz push do código para o GitHub. O workflow em `.github/workflows/build.yml` compila o APK automaticamente. Descarrega o APK em **Actions → build → Artifacts**.

### Opção 2 — Localmente (Linux/WSL)

```bash
pip install buildozer
buildozer android debug
```

O APK gerado fica em `bin/doonli-1.0-debug.apk`.

## Instalar no telemóvel

1. Copia o ficheiro `.apk` para o telemóvel
2. Vai a **Definições → Segurança → Fontes desconhecidas** e activa
3. Abre o ficheiro APK no telemóvel e instala

## Estrutura do projeto

```
doonli/
├── main.py                  # Código principal
├── buildozer.spec           # Configuração de compilação
├── requirements.txt         # Dependências Python
├── README.md                # Este ficheiro
└── .github/
    └── workflows/
        └── build.yml        # Compilação automática GitHub Actions
```

## Autor

DoOn Li Security — v1.0
