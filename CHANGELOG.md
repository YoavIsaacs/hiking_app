# Changelog

## 0.1.0 (2026-10-19)


### Features

* **api:** add app factory, settings, health, CORS and request-id logging ([ed19bcf](https://github.com/YoavIsaacs/hiking_app/commit/ed19bcf4994d30ea5ad19745658f4bf3ea606f7f))
* **api:** clean operation ids and offline openapi export ([7cc48a9](https://github.com/YoavIsaacs/hiking_app/commit/7cc48a968a8e131a46ea39b7045fc9241731023c))
* **api:** FastAPI skeleton with health, settings, CORS and request-id logging (step 0.2) ([77726b0](https://github.com/YoavIsaacs/hiking_app/commit/77726b04e2a2a24bbe15f8ff6662fd794d16c31f))
* **api:** HIKE_ settings prefix and firebase cors policy ([d439a33](https://github.com/YoavIsaacs/hiking_app/commit/d439a3306b9c2f085d0678d80ee6b4ec2f33a62e))
* **api:** stub cors policy contract ([ccb8332](https://github.com/YoavIsaacs/hiking_app/commit/ccb8332dfa427e79b6df4d590e9502ff2f0fd9c7))
* **api:** stub operation-id and openapi export contract ([dfa94b0](https://github.com/YoavIsaacs/hiking_app/commit/dfa94b022d96014bae9cf7d1eb1fb4017eeebec4))
* **deploy:** Cloud Run + Firebase Hosting via WIF (step 0.5) ([3398338](https://github.com/YoavIsaacs/hiking_app/commit/33983381bb652625cac1c7ac0190cc04db72f05d))
* generated API client and api-contract check (step 0.4) ([3688c57](https://github.com/YoavIsaacs/hiking_app/commit/3688c578f464b0fe5e3fc9fd903a4fc7a96057e0))
* **tools:** deploy smoke and traffic helpers ([ff096db](https://github.com/YoavIsaacs/hiking_app/commit/ff096db7443bcde64a938a3ab9ae94511d4d2b1c))
* **tools:** stub deploy smoke tool ([f89d42a](https://github.com/YoavIsaacs/hiking_app/commit/f89d42a541583327f977649ff446e4a232af94d9))
* **web:** implement ErrorState and AppErrorBoundary ([80b4061](https://github.com/YoavIsaacs/hiking_app/commit/80b4061590e97347ceed5eef4911c55f7a6af473))
* **web:** implement health client with error classification ([3cec657](https://github.com/YoavIsaacs/hiking_app/commit/3cec6574fedd74f9446fec56059f6ba238c398dd))
* **web:** implement home page and limit query retries ([ab2d192](https://github.com/YoavIsaacs/hiking_app/commit/ab2d1928dc4aedaec52f38223192f138bff4cc1d))
* **web:** openapi-fetch client with raw-fetch lint guard ([7783b78](https://github.com/YoavIsaacs/hiking_app/commit/7783b78da0b36c1aa6fc8bb8f2282b6ab3ddd95d))
* **web:** React app with health status page, web-test and e2e CI (step 0.3) ([c4202b1](https://github.com/YoavIsaacs/hiking_app/commit/c4202b1fe775df42515c80c2a3b980e4e04215bc))
* **web:** typed stub for home page, client and error components ([3938952](https://github.com/YoavIsaacs/hiking_app/commit/3938952337c903e358566d8959ba2e2fc5e5e987))


### Bug Fixes

* **api:** check operation ids on included routers ([34e36fd](https://github.com/YoavIsaacs/hiking_app/commit/34e36fd6478d96b0045052805e722e0bc5b1b788))
* **api:** export VERSION build arg in Dockerfile ([6c50eb7](https://github.com/YoavIsaacs/hiking_app/commit/6c50eb728cdefdaa119db872ef45fcfc1be51da5))
* **api:** keep request id on unhandled errors and log tracebacks ([b12e8ad](https://github.com/YoavIsaacs/hiking_app/commit/b12e8adbd15ab520dfed44aa7d5cab9319c0d261))
* scope python gitignore rules to api/, add web tsc hook ([802b20b](https://github.com/YoavIsaacs/hiking_app/commit/802b20b1d86545ee757d4de62342c545826664c6))
* **tooling:** run just recipes with cmd on Windows ([70169b8](https://github.com/YoavIsaacs/hiking_app/commit/70169b8c360e182a3c68387ca1fc25ce70032ff6))
* **tooling:** run just recipes with Git sh on Windows, never WSL bash ([acf5ea8](https://github.com/YoavIsaacs/hiking_app/commit/acf5ea824a095c3d1b6183c091b9475f05ce159d))
* **tools:** retry http.client protocol errors in smoke ([e3947b5](https://github.com/YoavIsaacs/hiking_app/commit/e3947b5214ae43f3d347b2d3b87c7ee3c386f866))
* **web:** add per-attempt timeout to /health so the error shows within 10 s ([f8a4227](https://github.com/YoavIsaacs/hiking_app/commit/f8a4227403b20c646c229e1f365db14fc4929995))
* **web:** require VITE_API_URL and test base-URL handling ([b33a097](https://github.com/YoavIsaacs/hiking_app/commit/b33a097f5ada052e9bfe7e70dcc7bf01d9024de9))
* **web:** route errors rethrow to AppErrorBoundary instead of router default page ([7bc3138](https://github.com/YoavIsaacs/hiking_app/commit/7bc3138676735dfc04f6f7e190e3f75fb4a06459))


### Reverts

* **deploy:** restore real git_sha after 0.5 rollback checkpoint ([5e8e157](https://github.com/YoavIsaacs/hiking_app/commit/5e8e1576311f6e82f0e3e935e2a7dfaa3a4c2171))
* **deploy:** restore real git_sha after 0.5 rollback checkpoint ([68dc9ee](https://github.com/YoavIsaacs/hiking_app/commit/68dc9ee083ecc29aca802e8a414f5ffbaba57613))
