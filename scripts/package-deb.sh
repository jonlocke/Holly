#!/usr/bin/env bash
set -euo pipefail

APP_NAME="holly-ux"
APP_DIR="/opt/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
MAINTAINER="Clyde Maintainers"
DESCRIPTION="Clyde UX Flask application service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUT_DIR="${OUT_DIR:-${REPO_ROOT}/dist}"
VERSION="${VERSION:-}"
ARCH="${ARCH:-all}"
SKIP_PIP_INSTALL="${SKIP_PIP_INSTALL:-0}"
UPGRADE_PIP="${UPGRADE_PIP:-0}"

if [[ -z "${VERSION}" ]]; then
  if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    GIT_SHORT="$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
  else
    GIT_SHORT="local"
  fi
  VERSION="0.1.0+git$(date +%Y%m%d).${GIT_SHORT}"
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd dpkg-deb
require_cmd python3

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "python3-venv is required to build this package." >&2
  exit 1
fi

WORK_ROOT="$(mktemp -d)"
PKG_ROOT="${WORK_ROOT}/${APP_NAME}_${VERSION}"
STAGE_ROOT="${PKG_ROOT}"
DEBIAN_DIR="${STAGE_ROOT}/DEBIAN"
APP_STAGE_DIR="${STAGE_ROOT}${APP_DIR}"

cleanup() {
  rm -rf "${WORK_ROOT}"
}
trap cleanup EXIT

mkdir -p "${DEBIAN_DIR}" "${APP_STAGE_DIR}" "${STAGE_ROOT}/lib/systemd/system" "${STAGE_ROOT}/etc/default"

# Copy runtime assets into the installed application directory.
install -m 0644 "${REPO_ROOT}/main.py" "${APP_STAGE_DIR}/main.py"
install -m 0644 "${REPO_ROOT}/main-cyberpunk.py" "${APP_STAGE_DIR}/main-cyberpunk.py"
install -m 0644 "${REPO_ROOT}/requirements.txt" "${APP_STAGE_DIR}/requirements.txt"
install -m 0644 "${REPO_ROOT}/README.md" "${APP_STAGE_DIR}/README.md"
install -m 0644 "${REPO_ROOT}/LICENSE" "${APP_STAGE_DIR}/LICENSE"
cp -a "${REPO_ROOT}/templates" "${APP_STAGE_DIR}/templates"
cp -a "${REPO_ROOT}/static" "${APP_STAGE_DIR}/static"

# Build a self-contained virtualenv as part of packaging.
python3 -m venv "${APP_STAGE_DIR}/.venv"
if [[ "${UPGRADE_PIP}" == "1" ]]; then
  "${APP_STAGE_DIR}/.venv/bin/python" -m pip install --upgrade pip
fi

if [[ "${SKIP_PIP_INSTALL}" == "1" ]]; then
  echo "Skipping dependency installation (SKIP_PIP_INSTALL=1)."
else
  "${APP_STAGE_DIR}/.venv/bin/pip" install --no-cache-dir -r "${APP_STAGE_DIR}/requirements.txt"
fi

"${APP_STAGE_DIR}/.venv/bin/python" -m compileall -q "${APP_STAGE_DIR}"

# Install service unit and default runtime env file.
install -m 0644 "${REPO_ROOT}/packaging/systemd/${SERVICE_NAME}" "${STAGE_ROOT}/lib/systemd/system/${SERVICE_NAME}"
install -m 0644 "${REPO_ROOT}/packaging/etc/default/${APP_NAME}" "${STAGE_ROOT}/etc/default/${APP_NAME}"

INSTALLED_SIZE="$(du -sk "${STAGE_ROOT}" | awk '{print $1}')"

cat > "${DEBIAN_DIR}/control" <<CONTROL
Package: ${APP_NAME}
Version: ${VERSION}
Section: web
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Depends: adduser, systemd
Installed-Size: ${INSTALLED_SIZE}
Description: ${DESCRIPTION}
 Web UX service for Clyde, packaged with a dedicated Python virtualenv.
CONTROL

cat > "${DEBIAN_DIR}/conffiles" <<CONFFILES
/etc/default/${APP_NAME}
CONFFILES

cat > "${DEBIAN_DIR}/postinst" <<'POSTINST'
#!/usr/bin/env bash
set -e

APP_NAME="holly-ux"
SERVICE_NAME="${APP_NAME}.service"
APP_DIR="/opt/${APP_NAME}"

if ! id -u clyde >/dev/null 2>&1; then
  adduser --system --group --home /var/lib/${APP_NAME} --no-create-home clyde
fi

install -d -o clyde -g clyde /var/lib/${APP_NAME} /var/log/${APP_NAME}
chown -R clyde:clyde "${APP_DIR}" || true

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true

  if [[ "$1" == "configure" ]]; then
    systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
    if ! systemctl try-restart "${SERVICE_NAME}" >/dev/null 2>&1; then
      systemctl start "${SERVICE_NAME}" >/dev/null 2>&1 || true
    fi
  fi
fi

echo "${APP_NAME} installed."
echo "Edit /etc/default/${APP_NAME} for runtime environment settings."
echo "Service commands: systemctl status|restart|stop ${SERVICE_NAME}"
POSTINST

cat > "${DEBIAN_DIR}/prerm" <<'PRERM'
#!/usr/bin/env bash
set -e

APP_NAME="holly-ux"
SERVICE_NAME="${APP_NAME}.service"

if command -v systemctl >/dev/null 2>&1; then
  if [[ "$1" == "remove" ]]; then
    systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
    systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
  fi
fi
PRERM

cat > "${DEBIAN_DIR}/postrm" <<'POSTRM'
#!/usr/bin/env bash
set -e

APP_NAME="holly-ux"

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
fi

if [[ "$1" == "purge" ]]; then
  rm -rf /var/log/${APP_NAME} /var/lib/${APP_NAME}
fi
POSTRM

chmod 0755 "${DEBIAN_DIR}/postinst" "${DEBIAN_DIR}/prerm" "${DEBIAN_DIR}/postrm"

mkdir -p "${OUT_DIR}"
DEB_PATH="${OUT_DIR}/${APP_NAME}_${VERSION}_${ARCH}.deb"

# Build package with root ownership metadata for Debian compatibility.
dpkg-deb --build --root-owner-group "${STAGE_ROOT}" "${DEB_PATH}" >/dev/null

echo "Built package: ${DEB_PATH}"
echo
echo "Package metadata:"
dpkg-deb --info "${DEB_PATH}"
echo
echo "Installed files (sanity check):"
dpkg-deb --contents "${DEB_PATH}" | sed -n '1,200p'
