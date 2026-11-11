plugins {
    id("com.android.application")
}

// Build output goes outside the project (OneDrive would otherwise sync thousands of build files).
val outside = System.getenv("LOCALAPPDATA")?.let { file("$it/jarvis-android/build/launcher") }
if (outside != null) layout.buildDirectory.set(outside)

android {
    namespace = "dev.jarvis.tv"
    compileSdk = 35
    defaultConfig {
        applicationId = "dev.jarvis.tv"
        minSdk = 28
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            // signed with the local debug key so it installs on your own projector over adb
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
