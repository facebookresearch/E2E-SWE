#!/bin/bash
set -e

# Ground-truth solution for the whatwg-url task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the reference URL parser (ada) and a small driver, and writes an OFFLINE build script producing
# the /app/urlparse contract the grader expects (URL on stdin, optional base as argv[1] -> JSON
# components + exit 0, or non-zero on parse failure).
#
# ada is amalgamated into a single self-contained C++17 translation unit (ada.cpp/ada.h) by ada's
# own bundled script; the default build needs no external dependencies (simdutf is optional and
# disabled), so the build is fully offline after the clone -- the agent never sees this source.

git clone https://github.com/ada-url/ada.git /tmp/repo
cd /tmp/repo
git checkout v2.9.2          # pinned; last C++17 release (builds on the base image's g++ 11)

mkdir -p /app/ada-src
cp -a /tmp/repo/. /app/ada-src/
cd /app
rm -rf /tmp/repo

# The GT driver: reads the URL on stdin, optional base as argv[1], prints WHATWG components as JSON.
cat > /app/gt_driver.cpp <<'DRIVER'
#include "ada.h"
#include <cstdio>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string>
#include <string_view>

static void json_str(std::ostream& o, std::string_view s) {
  o << '"';
  for (unsigned char c : s) {
    switch (c) {
      case '"': o << "\\\""; break;
      case '\\': o << "\\\\"; break;
      case '\b': o << "\\b"; break;
      case '\f': o << "\\f"; break;
      case '\n': o << "\\n"; break;
      case '\r': o << "\\r"; break;
      case '\t': o << "\\t"; break;
      default:
        if (c < 0x20) { char buf[8]; std::snprintf(buf, sizeof(buf), "\\u%04x", c); o << buf; }
        else o << c;
    }
  }
  o << '"';
}

int main(int argc, char** argv) {
  std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
  ada::result<ada::url_aggregator> r;
  if (argc > 1) {
    auto base = ada::parse<ada::url_aggregator>(argv[1]);
    if (!base) return 1;
    r = ada::parse<ada::url_aggregator>(input, &base.value());
  } else {
    r = ada::parse<ada::url_aggregator>(input);
  }
  if (!r) return 1;
  auto& u = r.value();
  std::ostringstream o;
  o << "{";
  o << "\"href\":";     json_str(o, u.get_href());     o << ",";
  o << "\"protocol\":"; json_str(o, u.get_protocol()); o << ",";
  o << "\"username\":"; json_str(o, u.get_username()); o << ",";
  o << "\"password\":"; json_str(o, u.get_password()); o << ",";
  o << "\"host\":";     json_str(o, u.get_host());     o << ",";
  o << "\"hostname\":"; json_str(o, u.get_hostname()); o << ",";
  o << "\"port\":";     json_str(o, u.get_port());     o << ",";
  o << "\"pathname\":"; json_str(o, u.get_pathname()); o << ",";
  o << "\"search\":";   json_str(o, u.get_search());   o << ",";
  o << "\"hash\":";     json_str(o, u.get_hash());
  o << "}";
  std::cout << o.str();
  return 0;
}
DRIVER

# setup.sh builds the reference OFFLINE: amalgamate ada into one C++17 unit, then compile the driver
# against it. No `set -e` here so a build failure cannot abort the (no-set-e) test.sh that sources
# it; a failed build just leaves /app/urlparse missing and every case then fails.
cat > /app/setup.sh <<'EOF'
cd /app/ada-src && python3 singleheader/amalgamate.py >/tmp/amalgamate.log 2>&1
g++ -O2 -std=c++17 -I /app/ada-src/singleheader /app/gt_driver.cpp /app/ada-src/singleheader/ada.cpp -o /app/urlparse
EOF
