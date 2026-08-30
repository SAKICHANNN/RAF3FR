#include <dlfcn.h>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

namespace {

constexpr const char* kDefaultFramework =
    "/Applications/Phocus.app/Contents/Frameworks/HBUtil.framework/Versions/A/HBUtil";
constexpr const char* kDecryptSymbol =
    "_ZN17HBCryptoNameSpace7decryptERKNSt3__16vectorIhNS0_9allocatorIhEEEERS4_"
    "PNS0_12basic_stringIcNS0_11char_traitsIcEENS2_IcEEEE";

using Decrypt = bool (*)(const std::vector<std::uint8_t>&,
                         std::vector<std::uint8_t>&, std::string*);

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: probe_phocus_dat INPUT.dat OUTPUT.decoded\n";
    return 2;
  }

  std::ifstream input(argv[1], std::ios::binary);
  if (!input) {
    std::cerr << "cannot open input\n";
    return 3;
  }
  std::vector<std::uint8_t> encrypted(
      (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());

  void* framework = dlopen(kDefaultFramework, RTLD_NOW | RTLD_LOCAL);
  if (!framework) {
    std::cerr << "cannot load HBUtil: " << dlerror() << "\n";
    return 4;
  }
  auto decrypt = reinterpret_cast<Decrypt>(dlsym(framework, kDecryptSymbol));
  if (!decrypt) {
    std::cerr << "cannot resolve decrypt entry point: " << dlerror() << "\n";
    dlclose(framework);
    return 5;
  }

  std::vector<std::uint8_t> decoded;
  std::string error;
  const bool ok = decrypt(encrypted, decoded, &error);
  if (!ok || decoded.empty()) {
    std::cerr << "decrypt failed";
    if (!error.empty()) std::cerr << ": " << error;
    std::cerr << "\n";
    dlclose(framework);
    return 6;
  }

  std::ofstream output(argv[2], std::ios::binary | std::ios::trunc);
  output.write(reinterpret_cast<const char*>(decoded.data()),
               static_cast<std::streamsize>(decoded.size()));
  if (!output) {
    std::cerr << "cannot write output\n";
    dlclose(framework);
    return 7;
  }
  std::cout << "decoded " << encrypted.size() << " -> " << decoded.size()
            << " bytes\n";
  dlclose(framework);
  return 0;
}
