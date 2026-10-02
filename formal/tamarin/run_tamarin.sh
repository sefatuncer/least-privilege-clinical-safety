#!/usr/bin/env bash
# Pilot: Tamarin 1.12.0 + Maude'u resmî ubuntu:24.04 imajında kurar ve modeli ispatlar.
# Çalıştırma: docker run --rm -v <bu klasör>:/work ubuntu:24.04 bash /work/run_tamarin.sh <model.spthy>
MODEL="${1:-pilot_mandate.spthy}"
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8 LC_ALL=C.UTF-8   # model dosyalarındaki UTF-8 yorumlar için gerekli
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq maude wget ca-certificates graphviz >/dev/null 2>&1
wget -q https://github.com/tamarin-prover/tamarin-prover/releases/download/1.12.0/tamarin-prover-1.12.0-linux64-ubuntu.tar.gz -O /tmp/t.tgz
tar xzf /tmp/t.tgz -C /usr/local/bin
echo "maude path: $(command -v maude)"
maude --version 2>&1 | head -1
tamarin-prover --version 2>&1 | head -3
start=$(date +%s%N)
tamarin-prover --prove "/work/${MODEL}" +RTS -N4 -RTS > "/work/${MODEL%.spthy}.out" 2>&1
rc=$?
end=$(date +%s%N)
echo "tamarin rc=${rc}"
echo "prove wall ms: $(( (end - start) / 1000000 ))"
sed -n '/summary of summaries/,$p' "/work/${MODEL%.spthy}.out"
tail -5 "/work/${MODEL%.spthy}.out"
