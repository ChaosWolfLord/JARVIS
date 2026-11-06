plugins {
    id("com.android.application")
}

// Build output goes outside the project (OneDrive would otherwise sync thousands of build files).
val outside = System.getenv("LOCALAPPDATA")?.let { file("$it/jarvis-android/build/app") }
if (outside != null) layout.buildDirectory.set(outside)

android {
    namespace = "dev.jarvis.phone"
    compileSdk = 35
    defaultConfig {
        applicationId = "dev.jarvis.phone"
        minSdk = 29            // Android 10: the WebView then hands over the server's certificate, which the app compares with the pinned one
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            // not debuggable (no remote inspection of the page, no adb run-as), signed with the local debug key so it installs on your own phone
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
