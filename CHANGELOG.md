# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## [v0.1.1](https://github.com/Pinguteca/sdk-scaffold/compare/bc03b30558b553ddfc35650890884afa8c66c29a..v0.1.1) - 2026-10-18
#### Build
- (**cog**) create annotated tags without a shell hook - ([4c7da47](https://github.com/Pinguteca/sdk-scaffold/commit/4c7da477ddcef4c5ea430ce3b09859aa447a9fff)) - [@Pinguladora](https://github.com/Pinguladora)
- (**cog**) version the template with tags (#19) - ([bc03b30](https://github.com/Pinguteca/sdk-scaffold/commit/bc03b30558b553ddfc35650890884afa8c66c29a)) - [@Pinguladora](https://github.com/Pinguladora)
- (**copier**) keep the docs index and pubspec out of updates (#20) - ([6b5fc07](https://github.com/Pinguteca/sdk-scaffold/commit/6b5fc07ed1fe4789349dc20dd73a1d171b33614e)) - [@Pinguladora](https://github.com/Pinguladora)
- (**copier**) keep the docs index and pubspec out of updates (#20) - ([e84996d](https://github.com/Pinguteca/sdk-scaffold/commit/e84996de4681e37540387302086993f8a012d344)) - [@Pinguladora](https://github.com/Pinguladora)

- - -

## [v0.1.0](https://github.com/Pinguteca/sdk-scaffold/compare/26e9f101c4a5432e816006f0cda31f80d061a09e..v0.1.0) - 2026-10-17
#### Features
- (**template**) add dart language overlay - ([aca1d7f](https://github.com/Pinguteca/sdk-scaffold/commit/aca1d7fe68ced10a4a5466e5a687bf483b50ec1a)) - [@Pinguladora](https://github.com/Pinguladora)
- (**template**) add go.work for workspace-ready Go scaffolds - ([1654247](https://github.com/Pinguteca/sdk-scaffold/commit/16542477ee094bb1dbcb1a2f390f11d2e0c6bbdf)) - [@Pinguladora](https://github.com/Pinguladora)
- bootstrap Copier template for Pinguteca SDK libraries - ([26e9f10](https://github.com/Pinguteca/sdk-scaffold/commit/26e9f101c4a5432e816006f0cda31f80d061a09e)) - [@Pinguladora](https://github.com/Pinguladora)
#### Bug Fixes
- (**mise**) align kingfisher tasks with secret-scan workflow - ([1d8b310](https://github.com/Pinguteca/sdk-scaffold/commit/1d8b310bc10c6bd411c3686721a061853dc2cb5f)) - [@Pinguladora](https://github.com/Pinguladora)
- (**workflows**) persist octo-sts token for auto-commit step - ([9a0bffc](https://github.com/Pinguteca/sdk-scaffold/commit/9a0bffc72918f46068f864dbb9e16ee3ac24a33c)) - [@Pinguladora](https://github.com/Pinguladora)
#### Performance Improvements
- (**mise**) cache build, restore, test, pack, and sbom tasks - ([ecc6a40](https://github.com/Pinguteca/sdk-scaffold/commit/ecc6a40c8d5b6bfcc1e2be80dc90b43bd910a9ec)) - [@Pinguladora](https://github.com/Pinguladora)
- (**mise.ci**) cache ci:restore, ci:build, and ci:pack - ([fe97f75](https://github.com/Pinguteca/sdk-scaffold/commit/fe97f754ac7089f3c350afa9eb356bf1a5fb90a9)) - [@Pinguladora](https://github.com/Pinguladora)
#### Build
- (**cog**) version the template with tags (#15) - ([6b5a432](https://github.com/Pinguteca/sdk-scaffold/commit/6b5a432391ccf4a84671e1ff1f69435650e34788)) - [@Pinguladora](https://github.com/Pinguladora)
- (**copier**) keep go module files out of updates - ([352eead](https://github.com/Pinguteca/sdk-scaffold/commit/352eead4b8940ad76db9eeeb71697a6426b87964)) - [@Pinguladora](https://github.com/Pinguladora)
- (**copier**) record answers in rendered repos - ([612df89](https://github.com/Pinguteca/sdk-scaffold/commit/612df898eae3a3cf2d8b2d053b05df880cd249d4)) - [@Pinguladora](https://github.com/Pinguladora)
- (**copier**) keep instance-owned files out of updates - ([5ac04c2](https://github.com/Pinguteca/sdk-scaffold/commit/5ac04c2825a1592173ec84ae3a7cadd80c04abdf)) - [@Pinguladora](https://github.com/Pinguladora)
- (**dotnet**) select the SDK from global.json alone - ([d127434](https://github.com/Pinguteca/sdk-scaffold/commit/d1274349eaf5b9970e2561d20a213a6f016189b4)) - [@Pinguladora](https://github.com/Pinguladora)
- (**dotnet**) run every test project through MTP dotnet test - ([71bf67a](https://github.com/Pinguteca/sdk-scaffold/commit/71bf67a2f1c4c81ee2deab0eab06bc7131902e0a)) - [@Pinguladora](https://github.com/Pinguladora)
- (**go**) never switch toolchains on demand - ([b9d1948](https://github.com/Pinguteca/sdk-scaffold/commit/b9d194831f51d336a621cb722a9455107b9fd1e2)) - [@Pinguladora](https://github.com/Pinguladora)
- (**hk**) validate JSON instead of reformatting it (#18) - ([5ed0ca0](https://github.com/Pinguteca/sdk-scaffold/commit/5ed0ca0d9367e6f6835eb59f3b036681da59c171)) - [@Pinguladora](https://github.com/Pinguladora)
- (**hk**) keep copier's answers file out of yamlfmt - ([c53806b](https://github.com/Pinguteca/sdk-scaffold/commit/c53806bab62463151dba3cccc5fece9c0d7dedce)) - [@Pinguladora](https://github.com/Pinguladora)
- (**mise**) use the registry name for kingfisher (#17) - ([d53a737](https://github.com/Pinguteca/sdk-scaffold/commit/d53a7376a594ea0d408b703c7a3a3512f05b9b0b)) - [@Pinguladora](https://github.com/Pinguladora)
- (**mise**) pin copier - ([d6c36e9](https://github.com/Pinguteca/sdk-scaffold/commit/d6c36e9ef80e5a6ddaf45d47561726d935f516b9)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) embed PDBs and use idempotent gh release create - ([bf57831](https://github.com/Pinguteca/sdk-scaffold/commit/bf57831b84bd7a05e0cca2a1f7f7f8a932731b75)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) split NUGET_USER from vendor - ([e2fe970](https://github.com/Pinguteca/sdk-scaffold/commit/e2fe97098cec9e62ec2892f213ef1ee037f5bfe8)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) stop fighting copier-update on every render - ([7f3a108](https://github.com/Pinguteca/sdk-scaffold/commit/7f3a10844b89f719c646217d12ad8e70886c9e76)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) fix octo-sts trust policies against schema - ([fab46e2](https://github.com/Pinguteca/sdk-scaffold/commit/fab46e286ce293c07b8a4de3861fdf88d4a72291)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) add cog separator marker to CHANGELOG template - ([604d0c5](https://github.com/Pinguteca/sdk-scaffold/commit/604d0c5734543a2f3593a3256629a64121c64a19)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) port NuGet OIDC and MTP test path back to template - ([7632d13](https://github.com/Pinguteca/sdk-scaffold/commit/7632d1370e2043b514b6e23c6321ccfae193d359)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) keep SLSA provenance off the GitHub Release - ([3b05f92](https://github.com/Pinguteca/sdk-scaffold/commit/3b05f927c7018838a4f550678b75b970983ae20b)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scaffold**) exempt SLSA generator from SHA pinning - ([032e410](https://github.com/Pinguteca/sdk-scaffold/commit/032e4101c43bfb39743e778930cab2924c51fcc9)) - [@Pinguladora](https://github.com/Pinguladora)
#### CI
- (**build-dotnet**) run on every pull request - ([9a92050](https://github.com/Pinguteca/sdk-scaffold/commit/9a92050307e9db6f00b4f7351ba3f164017d274c)) - [@Pinguladora](https://github.com/Pinguladora)
- (**deps**) bump mise-action to v5 and setup-dart to v1.8 - ([edc95bc](https://github.com/Pinguteca/sdk-scaffold/commit/edc95bc2621a8ba968813a2ad02ffe04e68162fe)) - [@Pinguladora](https://github.com/Pinguladora)
- (**deps**) bump action pins to the ones sdk-core-go runs - ([c6183fc](https://github.com/Pinguteca/sdk-scaffold/commit/c6183fc9f5348d5a67aaaea3fc20a36a4a17608b)) - [@Pinguladora](https://github.com/Pinguladora)
- (**gha**) sync go.work.sum on pull requests (#16) - ([3d8a0e1](https://github.com/Pinguteca/sdk-scaffold/commit/3d8a0e17e6fe6447c5fa1660f2f0d715fefd93fe)) - [@Pinguladora](https://github.com/Pinguladora)
- (**gha**) test on the floor Go - ([ee96af0](https://github.com/Pinguteca/sdk-scaffold/commit/ee96af02dbf864d248b7226547e1018be6b32d51)) - [@Pinguladora](https://github.com/Pinguladora)
- (**gha**) run the Go build when any module changes - ([8c2f36a](https://github.com/Pinguteca/sdk-scaffold/commit/8c2f36a12d9dbf15722113e7e53731a2ba8817da)) - [@Pinguladora](https://github.com/Pinguladora)
- (**gha**) commit lockfiles as the real bot user - ([7ab2ee0](https://github.com/Pinguteca/sdk-scaffold/commit/7ab2ee0b864bf2fdc550ff1e1afa80286c1380ed)) - [@Pinguladora](https://github.com/Pinguladora)
- (**mise**) never restore the mise-action cache - ([ece459b](https://github.com/Pinguteca/sdk-scaffold/commit/ece459bf74c9f002ee97089d226103a530f448f4)) - [@Pinguladora](https://github.com/Pinguladora)
- (**octo-sts**) trust only the rendered language workflows - ([9fb3ca5](https://github.com/Pinguteca/sdk-scaffold/commit/9fb3ca5f3002c7c2ec2541e6cbbe8f2b4f816a8a)) - [@Pinguladora](https://github.com/Pinguladora)
- (**octo-sts**) issue repo tokens on pull requests - ([e8657a3](https://github.com/Pinguteca/sdk-scaffold/commit/e8657a30d95cb5eb56f0ed9bf78767c5c5fcd91a)) - [@Pinguladora](https://github.com/Pinguladora)
- (**release**) note why the SLSA generator is tag-pinned - ([2d5c19c](https://github.com/Pinguteca/sdk-scaffold/commit/2d5c19c2cffa317241184192067e88f9d2ef6549)) - [@Pinguladora](https://github.com/Pinguladora)
- (**release**) pass expression values through env - ([cec5353](https://github.com/Pinguteca/sdk-scaffold/commit/cec5353dbc8148ae20cc967fd0ff1d29602c4ac8)) - [@Pinguladora](https://github.com/Pinguladora)
- (**scheduled-release**) let checkout carry the push token - ([0f98cd7](https://github.com/Pinguteca/sdk-scaffold/commit/0f98cd742dca00fe29d6f0d1d1c9aa8cb3e1f5eb)) - [@Pinguladora](https://github.com/Pinguladora)
- (**svg-optimization**) commit with git instead of an action - ([c5bad8c](https://github.com/Pinguteca/sdk-scaffold/commit/c5bad8c85f659afdc2fde0c40b504823843510d1)) - [@Pinguladora](https://github.com/Pinguladora)
- (**verify-gha-integrity**) pin gh-actions-lockfile to a SHA - ([8bb60cb](https://github.com/Pinguteca/sdk-scaffold/commit/8bb60cbe86660a97290a4e173de95c0415b8721e)) - [@Pinguladora](https://github.com/Pinguladora)
- (**verify-gha-integrity**) commit with git instead of an action - ([0f3d951](https://github.com/Pinguteca/sdk-scaffold/commit/0f3d951b98f7d466a2e45bc168316c70c3783c48)) - [@Pinguladora](https://github.com/Pinguladora)
- (**workflows**) state why each job permission is granted - ([c4acd57](https://github.com/Pinguteca/sdk-scaffold/commit/c4acd57cdbe5a885d20db03815361efbdb626918)) - [@Pinguladora](https://github.com/Pinguladora)
- (**workflows**) tune git config before every checkout - ([206dc87](https://github.com/Pinguteca/sdk-scaffold/commit/206dc87f6e9455f46bee6dc2f727ad0f04a194b5)) - [@Pinguladora](https://github.com/Pinguladora)
- (**zizmor**) require a ref pin for the SLSA generator - ([2b2d8c8](https://github.com/Pinguteca/sdk-scaffold/commit/2b2d8c8b8e31da5ba9d298ea9013de65902729d7)) - [@Pinguladora](https://github.com/Pinguladora)
- drop the gitsign verify workflow from the template (#6) - ([ef30824](https://github.com/Pinguteca/sdk-scaffold/commit/ef3082455411f17da27d836a45b106e452a53e96)) - [@Pinguladora](https://github.com/Pinguladora)
- widen octo-sts pattern to cover push-to-main - ([32c8826](https://github.com/Pinguteca/sdk-scaffold/commit/32c88264cdbdd3eed41cb28525788fda5e0a55b6)) - [@Pinguladora](https://github.com/Pinguladora)
- relax harden-runner so Docker-based actions can run - ([b60e0d9](https://github.com/Pinguteca/sdk-scaffold/commit/b60e0d91ff8adda7858437c122f079a7228cda5f)) - [@Pinguladora](https://github.com/Pinguladora)
- update kingfisher tasks for 1.98 CLI changes - ([b868f4e](https://github.com/Pinguteca/sdk-scaffold/commit/b868f4e87d712a27a48e69359ff7ead0b4b39e59)) - [@Pinguladora](https://github.com/Pinguladora)
- re-pin gh-actions-lockfile after upstream force-push - ([a24290e](https://github.com/Pinguteca/sdk-scaffold/commit/a24290e251fc9761f60e64b196c630f493dc4e9b)) - [@Pinguladora](https://github.com/Pinguladora)

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).