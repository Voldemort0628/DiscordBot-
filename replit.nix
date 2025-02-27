{pkgs}: {
  deps = [
    pkgs.chromium
    pkgs.playwright-driver
    pkgs.gitFull
    pkgs.zlib
    pkgs.xcodebuild
    pkgs.postgresql
  ];
}
