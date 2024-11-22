#!/usr/bin/bash

if [ ! -f browser/locales/shipped-locales ]; then
  echo "ERROR: Run this script from the root of the Camoufox source code"
  exit 1
fi

rm -rf browser/locales/l10n
mkdir browser/locales/l10n

N=8
for i in $(seq $N); do echo; done
total=$(wc -l < browser/locales/shipped-locales)

echo_status() {
  printf "\033[$((($N - $n) + 1))A$@ %40s\r\033[$((($N - $n) + 1))B"
}

generate_locale() {
  if echo " en-US ca ja " | grep -q " $1 "; then
    echo_status "Skipping locale \"$1\""
    sleep 1
    echo_status
    return
  fi
  echo_status "Downloading locale \"$1\""
  wget -q -O browser/locales/l10n/$1.zip https://hg.mozilla.org/l10n-central/$1/archive/tip.zip
  echo_status "Extracting locale \"$1\""
  7z x -y -obrowser/locales/l10n browser/locales/l10n/$1.zip > /dev/null
  mv browser/locales/l10n/$1-*/ browser/locales/l10n/$1/
  rm -f browser/locales/l10n/$1.zip
  echo_status "Generating locale \"$1\""
  mv browser/locales/l10n/$1/browser/branding/official browser/locales/l10n/$1/browser/branding/camoufox
  find browser/locales/l10n/$1 -type f -exec sed -i -e 's/Mozilla Firefox/Camoufox/g' {} \;
  find browser/locales/l10n/$1 -type f -exec sed -i -e 's/Mozilla/Camoufox/g' {} \;
  find browser/locales/l10n/$1 -type f -exec sed -i -e 's/Firefox/Camoufox/g' {} \;
  echo_status "Done"
  sleep 0.3
  echo_status
}

while read in; do
  ((n=n%N)); ((n++==0)) && wait
  generate_locale $in &
done < browser/locales/shipped-locales

wait

printf "\033[$(($N))A\rGenerated $total locales %-40s\n"