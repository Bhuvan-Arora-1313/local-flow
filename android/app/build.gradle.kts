plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.localflow.remote"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.localflow.remote"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = false
        buildConfig = true
    }

    // island: floating island via an accessibility service (full experience).
    // keyboard: same dictation as a selectable keyboard, no accessibility
    // service -- for phones where Play Protect blocks sideloading apps that
    // declare one (installs from a browser link with no adb needed).
    // Same applicationId, so either can later be installed over the other.
    flavorDimensions += "mode"
    productFlavors {
        create("island") { dimension = "mode" }
        create("keyboard") { dimension = "mode" }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
