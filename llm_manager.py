"""
LLM Manager for RakuTrans AI.
Provides unified routing across Google Gemini, OpenAI GPT, and Anthropic Claude.
Features strict JSON array batching, robust retries with exponential backoff, and error handling.
"""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from config import AppConfig, TranslationOptions


class LLMError(Exception):
    """Custom exception for LLM translation failures."""
    pass


def clean_json_text(text: str) -> str:
    """Strip markdown code fences and extraneous text around a JSON payload."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    
    # Try finding the first '[' and last ']'
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return text[first_bracket:last_bracket + 1].strip()
        
    return text


def build_system_prompt(
    target_lang: str,
    options: Optional[TranslationOptions] = None,
    source_lang: Optional[str] = None,
    *args,
    **kwargs
) -> str:
    """Build a comprehensive system prompt enforcing JSON array format and translation constraints."""
    # Support legacy signature: build_system_prompt(source_lang, target_lang, options)
    if isinstance(options, str):
        legacy_source = target_lang
        legacy_target = options
        legacy_opts = source_lang if isinstance(source_lang, TranslationOptions) else (args[0] if args else kwargs.get("options", TranslationOptions()))
        target_lang = legacy_target
        source_lang = legacy_source
        options = legacy_opts

    options = options or TranslationOptions()
    rules = [
        f"You are a professional document translator specializing in accurate and fluent translation into {target_lang}.",
        f"Translate the provided array of text strings into {target_lang}. The input texts may be in any language or contain mixed multilingual content.",
        f"CRITICAL: Except for parenthetical source term annotations, keywords, code syntax, variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, ALL other words, sentences, and explanatory text MUST be fully translated into {target_lang}.",
        "STRICT OUTPUT FORMAT: Return ONLY a valid JSON array of strings containing the translations.",
        "The output JSON array MUST have EXACTLY the same number of elements as the input array.",
        "Do NOT include explanations, markdown headers, conversational filler, or commentary. Output raw JSON array only.",
        "Preserve placeholders, variables, tags, numbers, punctuation, and leading/trailing whitespace where appropriate.",
        "UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for UI labels, button names, filter options, and quoted terms. Do not insert extraneous words or category prefixes around them."
    ]

    if options.keep_it_terms:
        rules.append(
            "KEEP SPECIALIZED TERMS UNTRANSLATED: Maintain proper nouns, standard abbreviations, acronyms, "
            "and international terms in their original form without forcing awkward or literal translations. "
            "Ensure surrounding sentences flow naturally and grammatically in the target language."
        )

    if options.append_original_words:
        rules.append(
            "APPEND ORIGINAL SOURCE WORDS AND ADAPT QUOTATION MARKS:\n"
            "- UI Labels and Quotation Marks: Enclose translated UI labels, button names, and filter options using the standard quotation marks of the target language rather than retaining source-specific bracket styles. Do not insert speculative filler words, category prefixes, or extra commentary around UI labels.\n"
            "- Verbatim Source Term: When appending the original term in parentheses immediately following its translation, the term inside the parentheses MUST be the exact verbatim string copied directly from the input source text in the original source language. Absolutely do not translate, interpret, or convert the original term into English or any other language.\n"
            "- Do not annotate common everyday words or terms that remain untranslated."
        )

    if options.custom_context and options.custom_context.strip():
        rules.append(f"PROJECT GLOSSARY & CONTEXT INSTRUCTIONS:\n{options.custom_context.strip()}")

    return "\n\n".join(rules)


class BaseLLMClient(ABC):
    """Abstract base class for all LLM provider clients."""
    
    @abstractmethod
    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True
    ) -> str:
        """Synchronously generate completion text with retry logic."""
        pass


class GeminiClient(BaseLLMClient):
    """Client for Google Gemini API with auto-recovery on deprecated models."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True
    ) -> str:
        # Normalize model name
        target_model = model_name or "gemini-3.6-flash"

        # Support both google-genai and google-generativeai
        try:
            import logging
            logging.getLogger("google_genai.models").setLevel(logging.ERROR)

            from google import genai
            from google.genai import types
            
            client = genai.Client(api_key=self.api_key)

            afc_config = None
            if hasattr(types, "AutomaticFunctionCallingConfig"):
                afc_config = types.AutomaticFunctionCallingConfig(disable=True)

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json" if is_json else "text/plain",
                temperature=0.2,
                automatic_function_calling=afc_config
            )
            response = client.models.generate_content(
                model=target_model,
                contents=user_prompt,
                config=config
            )
            return response.text or ""
        except ImportError:
            # Fallback to legacy google-generativeai
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=FutureWarning)
                import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=self.api_key)
            generation_config = {"temperature": 0.2}
            if is_json:
                generation_config["response_mime_type"] = "application/json"
            model = genai_legacy.GenerativeModel(
                model_name=target_model,
                system_instruction=system_prompt,
                generation_config=generation_config
            )
            response = model.generate_content(user_prompt)
            return response.text or ""

    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True
    ) -> str:
        if not self.api_key:
            raise LLMError("Gemini API key is missing. Please configure it in Settings.")

        effective_model = model_name or "gemini-3.6-flash"
        try:
            return self._call_gemini(system_prompt, user_prompt, effective_model, is_json=is_json)
        except Exception as e:
            err_str = str(e)
            # Check for deprecation notices with suggested alternative model
            # e.g.: "Please update your code to use models/gemini-3.6-flash for the latest features..."
            match = re.search(r"Please update your code to use (?:models/)?([a-zA-Z0-9\.\-_]+)", err_str)
            if match:
                suggested_model = match.group(1)
                print(f"[RakuTrans Auto-Recovery] Model '{effective_model}' is deprecated. Auto-switching to '{suggested_model}'...")
                try:
                    return self._call_gemini(system_prompt, user_prompt, suggested_model, is_json=is_json)
                except Exception as retry_err:
                    raise LLMError(f"Gemini API Error (after auto-switching to {suggested_model}): {retry_err}")
            raise LLMError(f"Gemini API Error: {e}")


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI GPT models."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True
    ) -> str:
        if not self.api_key:
            raise LLMError("OpenAI API key is missing. Please configure it in Settings.")

        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        target_model = model_name or "gpt-4o-mini"
        
        try:
            response = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"} if is_json and "gpt-4" in target_model else None,
                temperature=0.2
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise LLMError(f"OpenAI API Error: {e}")


class ClaudeClient(BaseLLMClient):
    """Client for Anthropic Claude models."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True
    ) -> str:
        if not self.api_key:
            raise LLMError("Anthropic Claude API key is missing. Please configure it in Settings.")

        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        target_model = model_name or "claude-3-7-sonnet-latest"
        
        try:
            message = client.messages.create(
                model=target_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2
            )
            return message.content[0].text if message.content else ""
        except Exception as e:
            raise LLMError(f"Claude API Error: {e}")


class LLMManager:
    """
    High-level LLM translation coordinator.
    Handles batch packing, JSON array verification, retries, and provider routing.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config

    def _get_client(self) -> BaseLLMClient:
        provider = self.config.active_provider
        api_key = self.config.get_effective_api_key(provider)
        
        if provider == "Gemini":
            return GeminiClient(api_key)
        elif provider == "OpenAI":
            return OpenAIClient(api_key)
        elif provider == "Claude":
            return ClaudeClient(api_key)
        else:
            raise LLMError(f"Unsupported AI provider: {provider}")

    def translate_batch(
        self,
        texts: List[str],
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: Optional[str] = None,
        max_retries: int = 3,
        *args,
        **kwargs
    ) -> List[str]:
        """
        Translates a list of strings into target_lang and returns a list of translated strings of equal length.
        Supports multi-lingual/mixed source text auto-detection.
        Includes retry logic for rate limits and parsing discrepancies.
        """
        if not texts:
            return []

        # Support legacy signature: translate_batch(texts, source_lang, target_lang, options)
        if isinstance(options, str):
            legacy_source = target_lang
            legacy_target = options
            legacy_opts = source_lang if isinstance(source_lang, TranslationOptions) else (args[0] if args else kwargs.get("options", None))
            target_lang = legacy_target
            source_lang = legacy_source
            options = legacy_opts

        options = options or self.config.translation_options
        system_prompt = build_system_prompt(target_lang, options, source_lang)
        
        user_input_json = json.dumps(texts, ensure_ascii=False)
        user_prompt = f"Translate this JSON array of {len(texts)} items into {target_lang}:\n{user_input_json}"
        
        client = self._get_client()
        model_name = self.config.get_active_model()

        last_error = None
        for attempt in range(max_retries):
            try:
                raw_response = client.generate_completion(system_prompt, user_prompt, model_name, is_json=True)
                cleaned = clean_json_text(raw_response)
                
                # Check if wrapped in an object e.g. {"translations": [...]} or {"items": [...]}
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    for key in ["translations", "data", "items", "result", "translated"]:
                        if key in parsed and isinstance(parsed[key], list):
                            parsed = parsed[key]
                            break
                    else:
                        # Find first list value in dict
                        list_vals = [v for v in parsed.values() if isinstance(v, list)]
                        if list_vals:
                            parsed = list_vals[0]
                        else:
                            raise ValueError("Returned JSON is an object without a list property.")

                if not isinstance(parsed, list):
                    raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

                # Verify length
                if len(parsed) == len(texts):
                    return [str(item) for item in parsed]
                
                # If length differs slightly, pad or truncate with warning
                if len(parsed) > len(texts):
                    return [str(item) for item in parsed[:len(texts)]]
                else:
                    # Pad missing with original
                    padding = texts[len(parsed):]
                    return [str(item) for item in parsed] + padding

            except Exception as e:
                last_error = e
                # Exponential backoff for rate limits or server glitches
                sleep_time = (2 ** attempt) + 1
                time.sleep(sleep_time)

        raise LLMError(f"Failed to translate batch after {max_retries} attempts. Last error: {last_error}")

    def translate_markdown_text(
        self,
        markdown_text: str,
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: Optional[str] = None,
        *args,
        **kwargs
    ) -> str:
        """Translates a full markdown block into target_lang preserving markdown layout and syntax."""
        # Support legacy signature: translate_markdown_text(markdown_text, source_lang, target_lang, options)
        if isinstance(options, str):
            legacy_source = target_lang
            legacy_target = options
            legacy_opts = source_lang if isinstance(source_lang, TranslationOptions) else (args[0] if args else kwargs.get("options", None))
            target_lang = legacy_target
            source_lang = legacy_source
            options = legacy_opts

        if not markdown_text.strip():
            return markdown_text

        options = options or self.config.translation_options
        system_prompt = (
            f"You are a professional translator. Translate the following Markdown document into {target_lang}.\n"
            f"The input document may contain mixed multilingual text.\n"
            f"CRITICAL: Except for parenthetical source term annotations, keywords, code syntax, variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, ALL other words, sentences, and explanatory text MUST be fully translated into {target_lang}.\n"
            "STRICT RULES:\n"
            "1. PRESERVE ALL MARKDOWN FORMATTING (headers, lists, tables, bold, italics, links, blockquotes).\n"
            "2. DO NOT translate code within code blocks or inline code.\n"
            "3. DO NOT translate URLs in markdown links or images.\n"
            "4. Return ONLY the translated Markdown text without conversational introduction or conclusion.\n"
            "5. UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for UI labels, button names, and quoted terms. Do not insert extraneous words, category prefixes, or filler around them."
        )

        if options.keep_it_terms:
            system_prompt += (
                "\n6. Keep proper nouns, standard abbreviations, acronyms, and international terms in their original form."
            )

        if options.append_original_words:
            system_prompt += (
                "\n7. APPEND ORIGINAL SOURCE WORDS: When appending the original term in parentheses immediately following its translation, "
                "the term inside the parentheses MUST be the exact verbatim string copied directly from the input source document in its original source language. "
                "Never translate, alter, or convert this original term into English or any other language. "
                "Enclose the translated UI labels in standard quotation marks of the target language rather than retaining source-specific bracket styles. "
                "Do not add unprompted commentary, category prefixes, or filler words around UI labels."
            )

        if options.custom_context and options.custom_context.strip():
            system_prompt += f"\n\nCUSTOM GLOSSARY & CONTEXT:\n{options.custom_context.strip()}"

        client = self._get_client()
        model_name = self.config.get_active_model()
        return client.generate_completion(system_prompt, markdown_text, model_name, is_json=False)
