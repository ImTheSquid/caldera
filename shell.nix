{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  packages = with pkgs; [ arduino-cli avrdude uv python3 gnumake ollama ];
}
