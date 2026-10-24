// OpenGOAL for PS5 - the app's main(): everything lives in the engine library (app/shim/appmain.cpp).
#include <cstdlib>

int ps5_app_main();

int main() {
  const int rc = ps5_app_main();
  std::exit(rc);  // return to the PS5 home screen when the launcher or the game ends
}
