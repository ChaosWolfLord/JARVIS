plugins {
    id("com.android.application")
}

// Build output goes outside the project (OneDrive would otherwise sync thousands of build files).
val outside = System.getenv("LOCALAPPDATA")?.let { file("$it/jarvis-android/build/app") }
if (outside != null) layout.buildDirectory.set(outside)

// The chat page is bundled inside the app too (it is the same page the PC serves), for use when the PC can't be reached.
val phonePage = layout.buildDirectory.get().asFile.resolve("generated/phone-page")
val copyPhonePage = tasks.register<Copy>("copyPhonePage") {
    from("../../web/phone")
    into(phonePage.resolve("phone"))
}

android {
    namespace = "dev.jarvis.phone"
    compileSdk = 35
    defaultConfig {
        applicationId = "dev.jarvis.phone"
        minSdk = 29            // Android 10: the WebView then hands over the server's certificate, which the app compares with the pinned one
        targetSdk = 34
        versionCode = 6
        versionName = "1.2.3"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            // not debuggable (no remote inspection of the page, no adb run-as), signed with the local debug key so it installs on your own phone
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    sourceSets.getByName("main").assets.srcDir(phonePage)
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

// the copy has to be finished before anything (merging assets, lint, packaging) reads the folder it fills
tasks.named("preBuild") { dependsOn(copyPhonePage) }
tasks.configureEach {
    if (name != "copyPhonePage" && name != "clean") mustRunAfter(copyPhonePage)
}
