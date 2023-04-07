import json
import os
import pathlib


def read_generator_arguments(input_file):
    with open(input_file, mode='r', encoding='utf-8') as h:
        return json.load(h)


def get_generator_module(module_path):
    if not os.path.exists(module_path):
        raise

    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader('generator_files_module', module_path)
    generator_files_module = loader.load_module()
    return generator_files_module


class GeneratorConfig:

    def __init__(self, arguments_file):
        self.arguments_file = arguments_file
        self.arguments = read_generator_arguments(self.arguments_file)
        generator_files_module_path = os.path.normpath(self.arguments['generator_files'])
        generator_files_module = get_generator_module(generator_files_module_path)

        # Get template mapping (required)
        if not hasattr(generator_files_module, 'get_template_mapping'):
            raise NotImplementedError("Missing function 'get_template_mapping()' in generator module " + generator_files_module_path)
        self.mapping = generator_files_module.get_template_mapping()
        # Check that templates exist
        template_basepath = pathlib.Path(self.arguments['template_dir'])
        for template_filename in self.mapping.keys():
            assert (template_basepath / template_filename).exists(), \
                'Could not find template: ' + template_filename

        # Additional context (optional)
        self.additional_context = None
        if hasattr(generator_files_module, 'get_additional_context'):
            self.additional_context = generator_files_module.get_additional_context()

        # Keep case (optional)
        self.keep_case = False
        if hasattr(generator_files_module, 'should_keep_case'):
            self.keep_case = generator_files_module.should_keep_case()

        # Post-process callback (optional)
        self.post_process_callback = None
        if hasattr(generator_files_module, 'post_process_callback'):
            self.post_process_callback = generator_files_module.post_process_callback
