#!/usr/bin/env python3

import logging
import os

DEFAULT_PROGRESS_FILE_ENV_VARIABLE = 'EXECUTOR_PROGRESS_OUTPUT_FILE'


class ProgressReporterConfig(object):
    """This class is responsible for storing the progress reporter config."""

    def __init__(self,
                 max_bytes_read_per_line=1024,
                 max_message_length=512,
                 progress_output_env_variable=DEFAULT_PROGRESS_FILE_ENV_VARIABLE,
                 progress_output_name='stdout',
                 progress_regex_string='',
                 progress_sample_interval_ms=100,
                 sandbox_directory=''):
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
    task_id = environment.get('COOK_INSTANCE_ID')
    if task_id is None:
        raise Exception('Task unknown! COOK_INSTANCE_ID not set in environment.')

    sandbox_directory = environment.get('MESOS_SANDBOX', '')
    default_progress_output_key = 'EXECUTOR_DEFAULT_PROGRESS_OUTPUT_NAME'
    default_progress_output_name = environment.get(default_progress_output_key, f'{task_id}.progress')
    if sandbox_directory:
        default_progress_output_file = os.path.join(sandbox_directory, default_progress_output_name)
    else:
        default_progress_output_file = default_progress_output_name

    progress_output_env_key = 'EXECUTOR_PROGRESS_OUTPUT_FILE_ENV'
    progress_output_env_variable = environment.get(progress_output_env_key, DEFAULT_PROGRESS_FILE_ENV_VARIABLE)
    logging.info('Progress location environment variable is {}'.format(progress_output_env_variable))
    if progress_output_env_variable not in environment:
        logging.info('No entry found for {} in the environment'.format(progress_output_env_variable))

    max_bytes_read_per_line = max(int(environment.get('EXECUTOR_MAX_BYTES_READ_PER_LINE', 4 * 1024)), 128)
    max_message_length = max(int(environment.get('EXECUTOR_MAX_MESSAGE_LENGTH', 512)), 64)
    progress_output_name = environment.get(progress_output_env_variable, default_progress_output_file)
    progress_regex_string = environment.get('PROGRESS_REGEX_STRING', r'progress: ([0-9]*\.?[0-9]+), (.*)')
    progress_sample_interval_ms = max(int(environment.get('PROGRESS_SAMPLE_INTERVAL_MS', 1000)), 100)
    sandbox_directory = environment.get('MESOS_SANDBOX', '')

    logging.info('Max bytes read per line is {}'.format(max_bytes_read_per_line))
    logging.info('Progress message length is limited to {}'.format(max_message_length))
    logging.info('Progress output file is {}'.format(progress_output_name))
    logging.info('Progress regex is {}'.format(progress_regex_string))
    logging.info('Progress sample interval is {}'.format(progress_sample_interval_ms))
    logging.info('Sandbox location is {}'.format(sandbox_directory))

    return ProgressReporterConfig(max_bytes_read_per_line=max_bytes_read_per_line,
                                  max_message_length=max_message_length,
                                  progress_output_env_variable=progress_output_env_variable,
                                  progress_output_name=progress_output_name,
                                  progress_regex_string=progress_regex_string,
                                  progress_sample_interval_ms=progress_sample_interval_ms,
                                  sandbox_directory=sandbox_directory)
