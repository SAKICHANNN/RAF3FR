package com.raf3fr.app

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import org.junit.Rule
import org.junit.Test

class MainActivityTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun primaryConversionSurfaceAndLanguageControlAreVisible() {
        composeRule.onNodeWithTag("source_selector").assertIsDisplayed()
        composeRule.onNodeWithText("中").assertIsDisplayed()
        composeRule.onNodeWithText("EN").assertIsDisplayed()
        composeRule.onNodeWithTag("convert_action").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun languageControlSwitchesThePrimarySurfaceToEnglish() {
        composeRule.onNodeWithText("EN").performClick()
        composeRule.onNodeWithText("Settings").assertIsDisplayed()
        composeRule.onNodeWithText("Convert & Save 3FR").performScrollTo().assertIsDisplayed()
    }
}
