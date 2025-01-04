import os
import numpy as np
import torch
from onnxruntime import InferenceSession, SessionOptions, GraphOptimizationLevel, ExecutionMode
from loguru import logger

from .tts_base import TTSBaseModel
from .text_processing import phonemize, tokenize
from ..core.config import settings

class TTSCPUModel(TTSBaseModel):
    _instance = None
    _onnx_session = None

    @classmethod
    def initialize(cls, model_dir: str, model_path: str = None):
        """Initialize ONNX model for CPU inference"""
        if cls._onnx_session is None:
            # Try loading ONNX model
            onnx_path = os.path.join(model_dir, settings.onnx_model_path)
            if os.path.exists(onnx_path):
                logger.info(f"Loading ONNX model from {onnx_path}")
            else:
                logger.error(f"ONNX model not found at {onnx_path}")
                return None

            if not onnx_path:
                return None

            logger.info(f"Loading ONNX model from {onnx_path}")
            
            # Configure ONNX session for optimal performance
            session_options = SessionOptions()
            session_options.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
            session_options.intra_op_num_threads = 4  # Adjust based on CPU cores
            session_options.execution_mode = ExecutionMode.ORT_SEQUENTIAL

            # Configure CPU provider options
            provider_options = {
                'CPUExecutionProvider': {
                    'arena_extend_strategy': 'kNextPowerOfTwo',
                    'cpu_memory_arena_cfg': 'cpu:0'
                }
            }

            cls._onnx_session = InferenceSession(
                onnx_path,
                sess_options=session_options,
                providers=['CPUExecutionProvider'],
                provider_options=[provider_options]
            )
            
            return cls._onnx_session
        return cls._onnx_session

    @classmethod
    def process_text(cls, text: str, language: str) -> tuple[str, list[int]]:
        """Process text into phonemes and tokens
        
        Args:
            text: Input text
            language: Language code
            
        Returns:
            tuple[str, list[int]]: Phonemes and token IDs
        """
        phonemes = phonemize(text, language)
        tokens = tokenize(phonemes)
        tokens = [0] + tokens + [0]  # Add start/end tokens
        return phonemes, tokens

    @classmethod
    def generate_from_text(cls, text: str, voicepack: torch.Tensor, language: str, speed: float) -> tuple[np.ndarray, str]:
        """Generate audio from text
        
        Args:
            text: Input text
            voicepack: Voice tensor
            language: Language code
            speed: Speed factor
            
        Returns:
            tuple[np.ndarray, str]: Generated audio samples and phonemes
        """
        if cls._onnx_session is None:
            raise RuntimeError("ONNX model not initialized")
            
        # Process text
        phonemes, tokens = cls.process_text(text, language)
        
        # Generate audio
        audio = cls.generate_from_tokens(tokens, voicepack, speed)
        
        return audio, phonemes

    @classmethod
    def generate_from_tokens(cls, tokens: list[int], voicepack: torch.Tensor, speed: float) -> np.ndarray:
        """Generate audio from tokens
        
        Args:
            tokens: Token IDs
            voicepack: Voice tensor
            speed: Speed factor
            
        Returns:
            np.ndarray: Generated audio samples
        """
        if cls._onnx_session is None:
            raise RuntimeError("ONNX model not initialized")

        # Pre-allocate and prepare inputs
        tokens_input = np.array([tokens], dtype=np.int64)
        style_input = voicepack[len(tokens)-2].numpy()  # Already has correct dimensions
        speed_input = np.full(1, speed, dtype=np.float32)  # More efficient than ones * speed
        
        # Run inference with optimized inputs
        result = cls._onnx_session.run(
            None,
            {
                'tokens': tokens_input,
                'style': style_input,
                'speed': speed_input
            }
        )
        return result[0]
