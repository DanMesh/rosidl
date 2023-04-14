# Copyright 2015 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from io import StringIO
from multiprocessing import Pool
import json
import os
import pathlib
import re
import sys
import time

import em
from rosidl_cmake.generator_config import GeneratorConfig
from rosidl_parser.definition import IdlLocator
from rosidl_parser.parser import parse_idl_file


def convert_camel_case_to_lower_case_underscore(value):
    # insert an underscore before any upper case letter
    # which is not followed by another upper case letter
    value = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', value)
    # insert an underscore before any upper case letter
    # which is preseded by a lower case letter or number
    value = re.sub('([a-z0-9])([A-Z])', r'\1_\2', value)
    return value.lower()


def read_generator_arguments(input_file):
    with open(input_file, mode='r', encoding='utf-8') as h:
        return json.load(h)


def get_newest_modification_time(target_dependencies):
    newest_timestamp = None
    for dep in target_dependencies:
        ts = os.path.getmtime(dep)
        if newest_timestamp is None or ts > newest_timestamp:
            newest_timestamp = ts
    return newest_timestamp


def generate_files(
    generator_arguments_file, mapping, additional_context=None,
    keep_case=False, post_process_callback=None
):
    args = read_generator_arguments(generator_arguments_file)

    out_string = "\nrosidl_cmake::generate_files:" + \
        "\n arg file   = " + generator_arguments_file + \
        "\n output dir = " + str(args['output_dir']) + \
        "\n idl_tuples = " + str(args['idl_tuples']) + \
        "\n add. ctxt. = " + (str(additional_context) if additional_context is not None else "[]") + \
        "\n"
    # print(out_string)

    template_basepath = pathlib.Path(args['template_dir'])
    for template_filename in mapping.keys():
        assert (template_basepath / template_filename).exists(), \
            'Could not find template: ' + template_filename

    latest_target_timestamp = get_newest_modification_time(args['target_dependencies'])
    generated_files = []

    time_parse_idl = 0.0
    time_expand_template = 0.0

    t_start = time.time()

    for idl_tuple in args.get('idl_tuples', []):
        out_string += " - idl_tuple =" + idl_tuple + "\n"
        idl_parts = idl_tuple.rsplit(':', 1)
        assert len(idl_parts) == 2
        locator = IdlLocator(*idl_parts)
        idl_rel_path = pathlib.Path(idl_parts[1])
        idl_stem = idl_rel_path.stem
        if not keep_case:
            idl_stem = convert_camel_case_to_lower_case_underscore(idl_stem)
        try:
            t_1 = time.time()
            idl_file = parse_idl_file(locator)
            t_2 = time.time()
            time_parse_idl += t_2 - t_1
            out_string += "   - parse_idl_file = " + str(t_2 - t_1) + "\n"
            out_string += "   - expand_template\n"
            for template_file, generated_filename in mapping.items():
                generated_file = os.path.join(
                    args['output_dir'], str(idl_rel_path.parent),
                    generated_filename % idl_stem)
                generated_files.append(generated_file)
                data = {
                    'package_name': args['package_name'],
                    'interface_path': idl_rel_path,
                    'content': idl_file.content,
                }
                if additional_context is not None:
                    data.update(additional_context)
                out_string += "     - exists? " + str(os.path.exists(generated_file))
                t_3 = time.time()
                # Generate the actual headers etc.
                expand_template(
                    os.path.basename(template_file), data,
                    generated_file, minimum_timestamp=latest_target_timestamp,
                    template_basepath=template_basepath,
                    post_process_callback=post_process_callback)
                t_4 = time.time()
                time_expand_template += t_4 - t_3
                out_string += " --> " + str(os.path.exists(generated_file)) + "\n"
                out_string += "     - " + str(t_4 - t_3) + " (" + generated_file + ")\n"
        except Exception as e:
            print(
                'Error processing idl file: ' +
                str(locator.get_absolute_path()), file=sys.stderr)
            raise(e)

    t_end = time.time()
    out_string += "time = " + str(t_end - t_start) + "\n"
    out_string += " - parse_idl_file  (all) " + str(time_parse_idl) + "\n"
    out_string += " - expand_template (all) " + str(time_expand_template) + "\n"

    out_string += "generated files:\n" + str(generated_files)
    print(out_string)

    return generated_files


def generate_files_for_idl_tuple(args):
    idl_tuple, configs_for_idl_tuple = args

    # Parse IDl file
    idl_parts = idl_tuple.rsplit(':', 1)
    assert len(idl_parts) == 2
    locator = IdlLocator(*idl_parts)
    idl_rel_path = pathlib.Path(idl_parts[1])
    try:
        idl_file = parse_idl_file(locator)

        # Generate code from templates according to each of the generator configs
        generated_files = []
        for config in configs_for_idl_tuple:
            template_basepath = pathlib.Path(config.arguments['template_dir'])
            for template_filename in config.mapping.keys():
                assert (template_basepath / template_filename).exists(), \
                    'Could not find template: ' + template_filename

            latest_target_timestamp = get_newest_modification_time(config.arguments['target_dependencies'])

            idl_stem = idl_rel_path.stem
            if not config.keep_case:
                idl_stem = convert_camel_case_to_lower_case_underscore(idl_stem)

            # IDL data
            data = {
                'package_name': config.arguments['package_name'],
                'interface_path': idl_rel_path,
                'content': idl_file.content,
            }
            if config.additional_context is not None:
                data.update(config.additional_context)

            # Expand templates
            for template_file, generated_filename in config.mapping.items():
                generated_file = os.path.join(
                    config.arguments['output_dir'], str(idl_rel_path.parent),
                    generated_filename % idl_stem)
                generated_files.append(generated_file)
                # Generate the actual headers etc.
                expand_template(
                    os.path.basename(template_file), data,
                    generated_file, minimum_timestamp=latest_target_timestamp,
                    template_basepath=template_basepath,
                    post_process_callback=config.post_process_callback)
        return generated_files

    except Exception as e:
        print('Error processing idl file: ' + str(locator.get_absolute_path()), file=sys.stderr)
        raise(e)


def generate_files_batch(arguments_files = []
):
    # Get mapping of IDL files to configs
    configs_for_idl_tuple = {}
    for arg_file in arguments_files:
        config = GeneratorConfig(arg_file)

        for idl_tuple in config.arguments.get('idl_tuples', []):
            idl_parts = idl_tuple.rsplit(':', 1)
            assert len(idl_parts) == 2

            if idl_tuple in configs_for_idl_tuple:
                configs_for_idl_tuple[idl_tuple].append(config)
            else:
                configs_for_idl_tuple[idl_tuple] = [config]

    t_start = time.time()
    pool = Pool()
    generated_files_per_idl_tuple = pool.map(generate_files_for_idl_tuple, ((idl_tuple, configs_for_idl_tuple[idl_tuple]) for idl_tuple in configs_for_idl_tuple.keys()))
    generated_files = [ file for file_list in generated_files_per_idl_tuple for file in file_list ]
    t_end = time.time()

    print("GENERATED BATCH!!! " + str(len(generated_files)) + " files in " + str(t_end - t_start) + "s")

    return generated_files


template_prefix_path = []


def get_template_path(template_name):
    global template_prefix_path
    for basepath in template_prefix_path:
        template_path = basepath / template_name
        if template_path.exists():
            return template_path
    raise RuntimeError(f"Failed to find template '{template_name}'")


interpreter = None


def expand_template(
    template_name, data, output_file, minimum_timestamp=None,
    template_basepath=None, post_process_callback=None
):
    # in the legacy API the first argument was the path to the template
    if template_basepath is None:
        template_name = pathlib.Path(template_name)
        template_basepath = template_name.parent
        template_name = template_name.name

    global interpreter
    output = StringIO()
    interpreter = em.Interpreter(
        output=output,
        options={
            em.BUFFERED_OPT: True,
            em.RAW_OPT: True,
        },
    )

    global template_prefix_path
    template_prefix_path.append(template_basepath)
    template_path = get_template_path(template_name)

    # create copy before manipulating
    data = dict(data)
    _add_helper_functions(data)

    try:
        with template_path.open('r') as h:
            template_content = h.read()
            interpreter.invoke(
                'beforeFile', name=template_name, file=h, locals=data)
        interpreter.string(template_content, template_path, locals=data)
        interpreter.invoke('afterFile')
    except Exception as e:  # noqa: F841
        if os.path.exists(output_file):
            os.remove(output_file)
        print(f"{e.__class__.__name__} when expanding '{template_name}' into "
              f"'{output_file}': {e}", file=sys.stderr)
        raise
    finally:
        template_prefix_path.pop()

    content = output.getvalue()
    interpreter.shutdown()

    if post_process_callback:
        content = post_process_callback(content)

    # only overwrite file if necessary
    # which is either when the timestamp is too old or when the content is different
    if os.path.exists(output_file):
        timestamp = os.path.getmtime(output_file)
        if minimum_timestamp is None or timestamp > minimum_timestamp:
            with open(output_file, 'r', encoding='utf-8') as h:
                if h.read() == content:
                    return
    else:
        # create folder if necessary
        try:
            os.makedirs(os.path.dirname(output_file))
        except FileExistsError:
            pass

    with open(output_file, 'w', encoding='utf-8') as h:
        h.write(content)


def _add_helper_functions(data):
    data['TEMPLATE'] = _expand_template


def _expand_template(template_name, **kwargs):
    global interpreter
    template_path = get_template_path(template_name)
    _add_helper_functions(kwargs)
    with template_path.open('r') as h:
        interpreter.invoke(
            'beforeInclude', name=str(template_path), file=h, locals=kwargs)
        content = h.read()
    try:
        interpreter.string(content, str(template_path), kwargs)
    except Exception as e:  # noqa: F841
        print(f"{e.__class__.__name__} in template '{template_path}': {e}",
              file=sys.stderr)
        raise
    interpreter.invoke('afterInclude')
