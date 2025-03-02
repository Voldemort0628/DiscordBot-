{pkgs}: {
  deps = [
    pkgs.libsodium
    pkgs.cacert
    pkgs.geckodriver
    pkgs.chromium
    pkgs.playwright-driver
    pkgs.gitFull
    pkgs.zlib
    pkgs.xcodebuild
    pkgs.postgresql
  ];
}
