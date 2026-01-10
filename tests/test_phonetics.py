"""
Unit tests for phonetics service
Tests CSV parsing, SSML injection, and validation
"""
import pytest
import tempfile
from pathlib import Path
from backend.services.phonetics import PhoneticsService, PronunciationRule


class TestPhoneticsParser:
    """Test CSV parsing functionality"""

    def test_load_valid_csv(self):
        """Test loading valid pronunciation CSV"""
        # Create temporary CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("source,target,mode\n")
            f.write("Wehrmacht,wermacht,sub\n")
            f.write("Führer,fiurer,sub\n")
            f.write("Test,tɛst,phoneme_ipa\n")
            csv_path = f.name

        try:
            service = PhoneticsService(csv_path=csv_path)

            assert len(service.rules) == 3
            assert service.rules[0].source == "Wehrmacht"
            assert service.rules[0].target == "wermacht"
            assert service.rules[0].mode == "sub"

            assert service.rules[2].mode == "phoneme_ipa"

        finally:
            Path(csv_path).unlink()

    def test_skip_invalid_rows(self):
        """Test that invalid CSV rows are skipped"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("source,target,mode\n")
            f.write("Valid,valid,sub\n")
            f.write("Missing,,sub\n")  # Missing target
            f.write(",,\n")  # Empty row
            f.write("Invalid,target,invalid_mode\n")  # Invalid mode
            csv_path = f.name

        try:
            service = PhoneticsService(csv_path=csv_path)

            # Only 1 valid rule should be loaded
            assert len(service.rules) == 1
            assert service.rules[0].source == "Valid"

        finally:
            Path(csv_path).unlink()

    def test_nonexistent_csv(self):
        """Test handling of non-existent CSV file"""
        service = PhoneticsService(csv_path="/nonexistent/path.csv")

        # Should not crash, just have empty rules
        assert len(service.rules) == 0


class TestSSMLInjection:
    """Test SSML tag injection"""

    def setup_method(self):
        """Setup test phonetics service"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("source,target,mode\n")
            f.write("Wehrmacht,wermacht,sub\n")
            f.write("Führer,fiurer,sub\n")
            f.write("Test,tɛst,phoneme_ipa\n")
            self.csv_path = f.name

        self.service = PhoneticsService(csv_path=self.csv_path)

    def teardown_method(self):
        """Cleanup"""
        Path(self.csv_path).unlink()

    def test_simple_substitution(self):
        """Test <sub> tag injection"""
        text = "The Wehrmacht was a powerful force."
        result = self.service.inject_ssml_tags(text)

        assert '<sub alias="wermacht">Wehrmacht</sub>' in result
        assert "powerful force" in result  # Unchanged text preserved

    def test_phoneme_injection(self):
        """Test <phoneme> tag injection"""
        text = "This is a Test of phonemes."
        result = self.service.inject_ssml_tags(text)

        assert '<phoneme alphabet="ipa" ph="tɛst">Test</phoneme>' in result

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive"""
        text = "The wehrmacht and WEHRMACHT and Wehrmacht."
        result = self.service.inject_ssml_tags(text)

        # All three variants should be tagged
        assert result.count('<sub alias="wermacht">') == 3
        assert "wehrmacht</sub>" in result
        assert "WEHRMACHT</sub>" in result
        assert "Wehrmacht</sub>" in result

    def test_whole_word_only(self):
        """Test that only whole words are matched"""
        text = "Wehrmacht in Wehrmachtssoldaten"
        result = self.service.inject_ssml_tags(text)

        # Only standalone "Wehrmacht" should be tagged
        assert result.count('<sub alias="wermacht">Wehrmacht</sub>') == 1
        # "Wehrmachtssoldaten" should NOT be tagged
        assert "Wehrmachtssoldaten</sub>" not in result

    def test_preserve_original_casing(self):
        """Test that original text casing is preserved in tags"""
        text = "FÜHRER and führer and Führer"
        result = self.service.inject_ssml_tags(text)

        # Original casing should be preserved inside tags
        assert "FÜHRER</sub>" in result
        assert "führer</sub>" in result
        assert "Führer</sub>" in result

    def test_no_nested_tags(self):
        """Test that tags don't get nested"""
        text = "Test Test"
        result = self.service.inject_ssml_tags(text)

        # Should not have nested <phoneme> tags
        assert "<phoneme" not in result.replace('<phoneme alphabet="ipa" ph="tɛst">Test</phoneme>', '', 1)

    def test_multiple_rules(self):
        """Test applying multiple rules to same text"""
        text = "The Wehrmacht under the Führer was tested."
        result = self.service.inject_ssml_tags(text)

        assert '<sub alias="wermacht">Wehrmacht</sub>' in result
        assert '<sub alias="fiurer">Führer</sub>' in result
        assert '<phoneme alphabet="ipa" ph="tɛst">tested</phoneme>' in result

    def test_empty_text(self):
        """Test handling empty text"""
        result = self.service.inject_ssml_tags("")
        assert result == ""

    def test_text_without_matches(self):
        """Test text with no matching rules"""
        text = "This text has no special words."
        result = self.service.inject_ssml_tags(text)

        assert result == text  # Should be unchanged


class TestSSMLValidation:
    """Test SSML validation"""

    def setup_method(self):
        """Setup test service"""
        self.service = PhoneticsService(csv_path="/dev/null")

    def test_valid_ssml(self):
        """Test validation of valid SSML"""
        text = 'Hello <sub alias="test">word</sub> and <phoneme alphabet="ipa" ph="test">another</phoneme>.'
        is_valid, error = self.service.validate_ssml(text)

        assert is_valid is True
        assert error == ""

    def test_mismatched_sub_tags(self):
        """Test detection of mismatched <sub> tags"""
        text = 'Hello <sub alias="test">word and another.'
        is_valid, error = self.service.validate_ssml(text)

        assert is_valid is False
        assert "Mismatched <sub> tags" in error

    def test_mismatched_phoneme_tags(self):
        """Test detection of mismatched <phoneme> tags"""
        text = 'Hello <phoneme alphabet="ipa" ph="test">word.'
        is_valid, error = self.service.validate_ssml(text)

        assert is_valid is False
        assert "Mismatched <phoneme> tags" in error


class TestStatistics:
    """Test statistics generation"""

    def setup_method(self):
        """Setup test service"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("source,target,mode\n")
            f.write("Test1,test1,sub\n")
            f.write("Test2,test2,phoneme_ipa\n")
            self.csv_path = f.name

        self.service = PhoneticsService(csv_path=self.csv_path)

    def teardown_method(self):
        """Cleanup"""
        Path(self.csv_path).unlink()

    def test_statistics(self):
        """Test getting statistics"""
        text = "Test1 and Test2 here."
        result = self.service.inject_ssml_tags(text)
        stats = self.service.get_statistics(result)

        assert stats["sub_tags"] == 1
        assert stats["phoneme_tags"] == 1
        assert stats["total_rules_applied"] == 2


# Run tests with: pytest tests/test_phonetics.py -v
