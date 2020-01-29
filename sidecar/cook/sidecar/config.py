#!/usr/bin/env python3

import logging
import os

DEFAULT_PROGRESS_FILE_ENV_VARIABLE = 'EXECUTOR_PROGRESS_OUTPUT_FILE'


class ProgressReporterConfig(object):
    """This class is responsible for storing the progress reporter config."""

    def __init__(self,
                 callback_url,
                 max_bytes_read_per_line=1024,
                 max_message_length=512,
                 progress_output_env_variable=DEFAULT_PROGRESS_FILE_ENV_VARIABLE,
                 progress_output_name='stdout',
                 progress_regex_string='',
                 progress_sample_interval_ms=100,
                 sandbox_directory=''):
        self.callback_url = callback_url
        self.max_bytes_read_per_line = max_bytes_read_per_line
        self.max_message_length = max_message_length
        self.progress_output_env_variable = progress_output_env_variable
        self.progress_output_name = progress_output_name
        self.progress_regex_string = progress_regex_string
        self.progress_sample_interval_ms = progress_sample_interval_ms
        self.sandbox_directory = sandbox_directory

    def sandbox_file(self, file):
        return os.path.join(self.sandbox_directory, file)

    def stderr_file(self):
        return self.sandbox_file('stderr')

    def stdout_file(self):
        return self.sandbox_file('stdout')


def initialize_config(environment):
    """Initializes the config using the environment.
    Populates the default values for missing environment variables.
    """
    instance_id = environment.get('COOK_INSTANCE_UUID')
    if instance_id is None:
        raise Exception('Task unknown! COOK_INSTANCE_UUID not set in environment.')

    cook_scheduler_rest_url = environment.get('COOK_SCHEDULER_REST_URL')
    if cook_scheduler_rest_url is None:
        raise Exception('REST URL unknown! COOK_SCHEDULER_REST_URL not set in environment.')

    callback_url = f'{cook_scheduler_rest_url}/progress/{instance_id}'

    sandbox_directory = environment.get('COOK_WORKDIR', '')
    default_progress_output_key = 'EXECUTOR_DEFAULT_PROGRESS_OUTPUT_NAME'
    default_progress_output_name = environment.get(default_progress_output_key, f'{instance_id}.progress')
    if sandbox_directory:
        default_progress_output_file = os.path.join(sandbox_directory, default_progress_output_name)
    else:
        default_progress_output_file = default_progress_output_name

    progress_output_env_key = 'EXECUTOR_PROGRESS_OUTPUT_FILE_ENV'
    progress_output_env_variable = environment.get(progress_output_env_key, DEFAULT_PROGRESS_FILE_ENV_VARIABLE)
    logging.info(f'Progress location environment variable is {progress_output_env_variable}')
    if progress_output_env_variable not in environment:
        logging.info(f'No entry found for {progress_output_env_variable} in the environment')

    max_bytes_read_per_line = max(int(environment.get('EXECUTOR_MAX_BYTES_READ_PER_LINE', 4 * 1024)), 128)
    max_message_length = max(int(environment.get('EXECUTOR_MAX_MESSAGE_LENGTH', 512)), 64)
    progress_output_name = environment.get(progress_output_env_variable, default_progress_output_file)
    progress_regex_string = environment.get('PROGRESS_REGEX_STRING', r'progress: ([0-9]*\.?[0-9]+), (.*)')
    progress_sample_interval_ms = max(int(environment.get('PROGRESS_SAMPLE_INTERVAL_MS', 1000)), 100)
    sandbox_directory = environment.get('COOK_WORKDIR', '')

    logging.info(f'Progress update callback url is {callback_url}')
    logging.info(f'Max bytes read per line is {max_bytes_read_per_line}')
    logging.info(f'Progress message length is limited to {max_message_length}')
    logging.info(f'Progress output file is {progress_output_name}')
    logging.info(f'Progress regex is {progress_regex_string}')
    logging.info(f'Progress sample interval is {progress_sample_interval_ms}')
    logging.info(f'Sandbox location is {sandbox_directory}')

    return ProgressReporterConfig(callback_url=callback_url,
                                  max_bytes_read_per_line=max_bytes_read_per_line,
                                  max_message_length=max_message_length,
                                  progress_output_env_variable=progress_output_env_variable,
                                  progress_output_name=progress_output_name,
                                  progress_regex_string=progress_regex_string,
                                  progress_sample_interval_ms=progress_sample_interval_ms,
                                  sandbox_directory=sandbox_directory)
