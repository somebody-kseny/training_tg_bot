#!/usr/bin/env bash
# Собирает zip для Yandex Cloud Functions: build/<name>.zip для каждой функции.
# Платформа сама делает pip install по requirements.txt при создании версии.
# https://yandex.cloud/docs/functions/lang/python/dependencies
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FUNCTIONS=(core proxy)
BUILD_DIR="${ROOT}/build"

mkdir -p "${BUILD_DIR}"

for name in "${FUNCTIONS[@]}"; do
  src_dir="${ROOT}/${name}"
  out_zip="${BUILD_DIR}/${name}.zip"

  if [[ ! -d "${src_dir}" ]]; then
    echo "Не найден каталог функции: ${src_dir}" >&2
    exit 1
  fi

  for required in index.py requirements.txt; do
    if [[ ! -e "${src_dir}/${required}" ]]; then
      echo "Не найден обязательный файл: ${src_dir}/${required}" >&2
      exit 1
    fi
  done

  zip_args=(index.py requirements.txt)
  if [[ -d "${src_dir}/bot" ]]; then
    zip_args+=(bot)
  fi

  rm -f "${out_zip}"
  (
    cd "${src_dir}"
    # Без macOS-мусора (__MACOSX, ._*): файлы в корне zip, не во вложенной папке.
    COPYFILE_DISABLE=1 zip -X -r "${out_zip}" "${zip_args[@]}" \
      -x '*__pycache__*' '*.pyc' '*.pyo' '*.DS_Store' '*/.*' 'bot/__main__.py' '.venv/*'
  )

  echo "Создан ${out_zip}"
  unzip -l "${out_zip}"
  echo
done
