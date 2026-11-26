plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Stable signing: CI supplies UMC_KEYSTORE_FILE / UMC_KEYSTORE_PASSWORD (alias "umc"). Without them
// the build falls back to the debug key, so local and fork builds never break.
val umcKeystore: java.io.File? = System.getenv("UMC_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }?.let { java.io.File(it) }?.takeIf { it.exists() }
val umcKeystorePassword: String = System.getenv("UMC_KEYSTORE_PASSWORD") ?: ""
// Ordered version codes from the CI run number, so each build can update the last one.
val umcRunNumber: Int? = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()
val umcGitSha: String = System.getenv("GITHUB_SHA")?.trim()?.take(7)?.takeIf { it.isNotEmpty() } ?: "dev"

android {
    namespace = "uk.umc.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "uk.umc.app"
        minSdk = 26
        targetSdk = 35
        versionCode = if (umcRunNumber != null) 100 + umcRunNumber else 16
        versionName = "0.1.15"
        buildConfigField("String", "GIT_SHA", "\"$umcGitSha\"")
    }

    signingConfigs {
        create("umc") {
            if (umcKeystore != null) {
                storeFile = umcKeystore
                storePassword = umcKeystorePassword
                keyAlias = "umc"
                keyPassword = umcKeystorePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Stable key when CI provides it, so every build can update the last. Otherwise the
            // debug key (a throwaway on CI: such builds cannot update over a differently signed install).
            signingConfig = if (umcKeystore != null) signingConfigs.getByName("umc") else signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
        // BouncyCastle brings duplicate metadata files
        resources.excludes += listOf("META-INF/INDEX.LIST", "META-INF/DEPENDENCIES", "META-INF/versions/**", "META-INF/LICENSE*", "META-INF/NOTICE*")
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("com.composables:icons-lucide-android:1.1.0")      // Lucide icons, the set shadcn/ui uses
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.osmdroid:osmdroid-android:6.1.20")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")             // UMC Net: WebSocket transport for the hand-written MQTT 3.1.1 codec
    implementation("org.bouncycastle:bcprov-jdk18on:1.78.1")         // UMC Net enrolment: Ed25519 and X25519 (lightweight API)
    implementation("androidx.security:security-crypto:1.1.0-alpha06") // UMC Net: encrypted storage for the login and keys
    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
}
